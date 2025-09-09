"""
routes/schedule.py

Módulo para gerenciar a agenda/calendário de eventos, como manutenções e reservas.
"""
from flask import Blueprint, render_template, jsonify, request
from models import Appointment, User, Client, db, SchedulingLink
from datetime import datetime, timezone
from flask_login import login_required
import traceback


# --- Configuração do Blueprint ---
schedule_bp = Blueprint('schedule', __name__, template_folder='templates')


# --- Rotas ---

@schedule_bp.route('/schedule/')
@login_required
def calendar_view():
    """
    Renderiza a página principal do calendário.
    """
    try:
        technicians = User.query.filter_by(role='technician', is_active=True).order_by(User.name).all()
        clients = Client.query.filter_by(is_archived=False).order_by(Client.name).all()
        
        return render_template(
            'schedule.html', 
            technicians=technicians, 
            clients=clients
        )
    except Exception as e:
        print(f"Erro ao carregar página do calendário: {str(e)}")
        print(traceback.format_exc())
        return render_template('error.html', message="Erro ao carregar calendário"), 500


@schedule_bp.route('/api/appointments')
@login_required
def api_get_appointments():
    """
    Endpoint de API que retorna todos os agendamentos em formato JSON.
    O calendário (FullCalendar.js) usará esta rota para buscar os eventos.
    """
    try:
        appointments = Appointment.query.all()
        
        events_list = []
        for appointment in appointments:
            try:
                # Definição da cor de acordo com status/tipo
                color = '#3788d8'  # Azul padrão
                if appointment.status == 'PENDING_APPROVAL':
                    color = '#FBBF24'  # Amarelo (aguardando aprovação)
                elif appointment.status == 'CANCELLED':
                    color = '#EF4444'  # Vermelho (cancelado)
                elif appointment.event_type == 'RESERVATION':
                    color = '#10B981'  # Verde (reserva)

                technician_name = appointment.technician.name if appointment.technician else 'Não definido'
                client_name = appointment.client.name if appointment.client else None

                event_data = {
                    'id': appointment.id,
                    'title': appointment.title,
                    'start': appointment.start_datetime.isoformat(),
                    'end': appointment.end_datetime.isoformat(),
                    'color': color,
                    'eventType': appointment.event_type,
                    'status': appointment.status,
                    'technicianName': technician_name,
                    'technicianId': appointment.user_id,
                    'clientName': client_name,
                    'clientId': appointment.client_id
                }
                
                events_list.append(event_data)
                
            except Exception as e:
                print(f"Erro ao processar appointment {appointment.id}: {str(e)}")
                continue
            
        return jsonify(events_list)

    except Exception as e:
        print(f"Erro ao buscar appointments: {str(e)}")
        print(traceback.format_exc())
        return jsonify({"error": "Falha ao buscar agendamentos", "message": str(e)}), 500


@schedule_bp.route('/api/appointments/create', methods=['POST'])
@login_required
def api_create_appointment():
    """
    Endpoint para criar um novo agendamento.
    """
    try:
        if not request.is_json:
            return jsonify({'status': 'error', 'message': 'Content-Type deve ser application/json'}), 400
        
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'Nenhum dado recebido.'}), 400

        required_fields = ['title', 'start', 'user_id']
        missing_fields = [f for f in required_fields if f not in data or not str(data[f]).strip()]
        if missing_fields:
            return jsonify({'status': 'error', 'message': f"Campos obrigatórios faltando: {', '.join(missing_fields)}"}), 400

        technician = User.query.get(data['user_id'])
        if not technician:
            return jsonify({'status': 'error', 'message': 'Técnico não encontrado.'}), 400

        client = None
        if data.get('client_id'):
            client = Client.query.get(data['client_id'])
            if not client:
                return jsonify({'status': 'error', 'message': 'Cliente não encontrado.'}), 400

        start_dt = datetime.fromisoformat(data['start'].replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(data.get('end', data['start']).replace('Z', '+00:00'))
        if end_dt <= start_dt:
            return jsonify({'status': 'error', 'message': 'A data/hora de fim deve ser posterior à de início.'}), 400

        new_appointment = Appointment(
            title=data['title'].strip(),
            start_datetime=start_dt,
            end_datetime=end_dt,
            client_id=client.id if client else None,
            user_id=technician.id,
            event_type=data.get('event_type', 'MAINTENANCE'),
            status='SCHEDULED',
            notes=data.get('notes', '')
        )
        
        db.session.add(new_appointment)
        db.session.commit()
        
        return jsonify({
            'status': 'success', 
            'message': 'Agendamento criado com sucesso!',
            'appointment_id': new_appointment.id
        }), 201

    except Exception as e:
        db.session.rollback()
        print(traceback.format_exc())
        return jsonify({'status': 'error', 'message': f'Erro interno: {str(e)}'}), 500


@schedule_bp.route('/api/appointments/<int:appointment_id>', methods=['GET'])
@login_required
def api_get_appointment(appointment_id):
    try:
        appointment = Appointment.query.get_or_404(appointment_id)
        return jsonify({
            'id': appointment.id,
            'title': appointment.title,
            'start': appointment.start_datetime.isoformat(),
            'end': appointment.end_datetime.isoformat(),
            'event_type': appointment.event_type,
            'status': appointment.status,
            'notes': appointment.notes,
            'technician_id': appointment.user_id,
            'technician_name': appointment.technician.name if appointment.technician else None,
            'client_id': appointment.client_id,
            'client_name': appointment.client.name if appointment.client else None
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@schedule_bp.route('/api/appointments/<int:appointment_id>', methods=['PUT'])
@login_required
def api_update_appointment(appointment_id):
    try:
        appointment = Appointment.query.get_or_404(appointment_id)
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'Nenhum dado recebido.'}), 400
        
        if 'title' in data: appointment.title = data['title'].strip()
        if 'start' in data: appointment.start_datetime = datetime.fromisoformat(data['start'].replace('Z', '+00:00'))
        if 'end' in data: appointment.end_datetime = datetime.fromisoformat(data['end'].replace('Z', '+00:00'))
        if 'user_id' in data:
            technician = User.query.get(data['user_id'])
            if not technician:
                return jsonify({'status': 'error', 'message': 'Técnico não encontrado.'}), 400
            appointment.user_id = technician.id
        if 'client_id' in data:
            appointment.client_id = data['client_id'] or None
        if 'status' in data: appointment.status = data['status']
        if 'notes' in data: appointment.notes = data['notes']
        
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Agendamento atualizado com sucesso!'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@schedule_bp.route('/api/appointments/<int:appointment_id>', methods=['DELETE'])
@login_required
def api_delete_appointment(appointment_id):
    try:
        appointment = Appointment.query.get_or_404(appointment_id)
        db.session.delete(appointment)
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Agendamento excluído com sucesso!'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    

@schedule_bp.route('/public/schedule/<string:token>')
def public_schedule_page(token):
    link = SchedulingLink.query.filter_by(token=token).first()
    if not link: return "Link de agendamento inválido.", 404
    if link.is_used: return "Este link já foi utilizado.", 410
    if datetime.utcnow() > link.expires_at: return "Este link expirou.", 410
    return render_template('public_schedule.html', client=link.client, link=link)


@schedule_bp.route('/api/public/schedule/create', methods=['POST'])
def api_public_create_appointment():
    data = request.get_json()
    token = data.get('token')
    link = SchedulingLink.query.filter_by(token=token).first()
    if not link or link.is_used or datetime.utcnow() > link.expires_at:
        return jsonify({'status': 'error', 'message': 'Link inválido ou expirado.'}), 403
    try:
        start_dt = datetime.fromisoformat(data['start']).replace(tzinfo=timezone.utc)
        end_dt = datetime.fromisoformat(data['end']).replace(tzinfo=timezone.utc)
        if start_dt < datetime.now(timezone.utc):
            return jsonify({'status': 'error', 'message': 'Não é possível agendar no passado.'}), 400

        new_appointment = Appointment(
            title=data.get('title', link.purpose),
            start_datetime=start_dt,
            end_datetime=end_dt,
            client_id=link.client_id,
            user_id=1,  # placeholder até aprovação
            status='PENDING_APPROVAL',
            notes=data.get('notes', '')
        )
        
        link.is_used = True
        db.session.add(new_appointment)
        db.session.add(link)
        db.session.commit()
        
        return jsonify({'status': 'success', 'message': 'Seu horário foi solicitado com sucesso!'}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@schedule_bp.route('/api/public/appointments')
def api_public_get_appointments():
    try:
        appointments = Appointment.query.filter(Appointment.status != 'CANCELLED').all()
        busy_slots = []
        for appointment in appointments:
            busy_slots.append({
                'start': appointment.start_datetime.isoformat(),
                'end': appointment.end_datetime.isoformat(),
                'display': 'background',
                'color': '#d1d5db'
            })
        return jsonify(busy_slots)
    except Exception as e:
        return jsonify({"error": "Falha ao buscar horários"}), 500

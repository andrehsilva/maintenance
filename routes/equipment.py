"""
routes/equipment.py

Gerenciamento completo de equipamentos, histórico de manutenção, uploads e relatórios.
"""

import os
import io
import uuid
import pandas as pd
from datetime import datetime, date
from werkzeug.utils import secure_filename
from sqlalchemy import desc
from sqlalchemy.orm import joinedload
from flask import (Blueprint, render_template, request, redirect, url_for, flash, abort, send_file, current_app)
from flask_login import login_required, current_user

# Importações do projeto
from models import (Equipment, Client, User, Notification, MaintenanceHistory,
                    StockItem, MaintenancePartUsed, MaintenanceImage)
from extensions import db
from .utils import admin_required, notify_admins, FUSO_HORARIO_SP

# --- Configurações do Blueprint ---
equipment_bp = Blueprint('equipment', __name__, template_folder='templates')

# --- Constantes e Funções Auxiliares do Módulo ---
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAINTENANCE_CATEGORIES = ['Instalação', 'Manutenção Preventiva', 'Manutenção Corretiva', 'Manutenção Proativa']

def allowed_file(filename):
    """Verifica se a extensão do arquivo é permitida."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- ROTAS DE GERENCIAMENTO DE EQUIPAMENTOS ---

@equipment_bp.route('/equipments')
@login_required
def equipment_list():
    """Exibe a lista de equipamentos ativos."""
    page = request.args.get('page', 1, type=int)
    per_page = 10
    if current_user.role == 'admin':
        q = Equipment.query.filter_by(is_archived=False).order_by(Equipment.next_maintenance_date.asc())
    else:
        q = Equipment.query.filter_by(user_id=current_user.id, is_archived=False).order_by(Equipment.next_maintenance_date.asc())
    equipments = q.paginate(page=page, per_page=per_page, error_out=False)
    return render_template('equipment_list.html', equipments=equipments)

@equipment_bp.route('/equipment/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_equipment():
    """Cadastra um novo equipamento."""
    clients = Client.query.filter_by(is_archived=False).order_by(Client.name).all()
    technicians = User.query.filter_by(role='technician').order_by(User.username).all()

    if not clients:
        flash('Você precisa cadastrar um cliente antes de adicionar um equipamento.', 'warning')
        return redirect(url_for('clients.new_client'))

    if request.method == 'POST':
        try:
            code = request.form.get('code')
            if Equipment.query.filter_by(code=code).first():
                flash(f'O código de equipamento "{code}" já existe.', 'warning')
                return render_template('equipment_form.html', title="Cadastrar Equipamento", clients=clients, technicians=technicians, equipment=None, form_data=request.form)

            assigned_user_id = request.form.get('technician_id')
            if not assigned_user_id:
                flash('Você deve designar um técnico responsável.', 'danger')
                return render_template('equipment_form.html', title="Cadastrar Equipamento", clients=clients, technicians=technicians, equipment=None, form_data=request.form)

            equipment = Equipment(
                code=code,
                model=request.form.get('model'),
                location=request.form.get('location'),
                description=request.form.get('description'),
                install_date=datetime.strptime(request.form.get('install_date'), '%Y-%m-%d').date() if request.form.get('install_date') else None,
                last_maintenance_date=datetime.strptime(request.form.get('last_maintenance_date'), '%Y-%m-%d').date() if request.form.get('last_maintenance_date') else None,
                next_maintenance_date=datetime.strptime(request.form.get('next_maintenance_date'), '%Y-%m-%d').date(),
                user_id=assigned_user_id,
                client_id=request.form.get('client_id')
            )
            db.session.add(equipment)
            db.session.commit()

            msg = f"Novo equipamento '{equipment.code}' foi cadastrado por {current_user.username}."
            url = url_for('equipment.equipment_history', equipment_id=equipment.id)
            notify_admins(msg, url, excluded_user_id=current_user.id)

            if int(assigned_user_id) != current_user.id:
                notif_technician = Notification(user_id=int(assigned_user_id), message=f"O equipamento '{equipment.code}' foi atribuído a você.", url=url)
                db.session.add(notif_technician)
            db.session.commit()

            flash('Equipamento cadastrado com sucesso!', 'success')
            return redirect(url_for('core.dashboard'))

        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar equipamento: {e}', 'danger')
            return render_template('equipment_form.html', title="Cadastrar Equipamento", clients=clients, technicians=technicians, equipment=None, form_data=request.form)

    today_date = date.today().strftime('%Y-%m-%d')
    form_data = {'install_date': today_date}
    return render_template('equipment_form.html', title="Cadastrar Novo Equipamento", clients=clients, technicians=technicians, equipment=None, form_data=form_data)


@equipment_bp.route('/equipment/edit/<int:equipment_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_equipment(equipment_id):
    """Edita um equipamento existente."""
    equipment = db.session.get(Equipment, equipment_id)
    if not equipment:
        abort(404)
    clients = Client.query.filter_by(is_archived=False).order_by(Client.name).all()
    technicians = User.query.filter_by(role='technician').order_by(User.username).all()
    if request.method == 'POST':
        try:
            new_code = request.form.get('code')
            existing_equipment = Equipment.query.filter(Equipment.code == new_code, Equipment.id != equipment_id).first()
            if existing_equipment:
                flash(f'O código de equipamento "{new_code}" já pertence a outro equipamento.', 'warning')
                return render_template('equipment_form.html', title="Editar Equipamento", clients=clients, technicians=technicians, equipment=equipment, form_data=request.form)
            
            assigned_user_id = request.form.get('technician_id')
            if not assigned_user_id:
                flash('Como administrador, você deve designar um técnico.', 'danger')
                return render_template('equipment_form.html', title="Editar Equipamento", clients=clients, technicians=technicians, equipment=equipment, form_data=request.form)

            equipment.code, equipment.model, equipment.location = new_code, request.form.get('model'), request.form.get('location')
            equipment.description = request.form.get('description')
            equipment.install_date = datetime.strptime(request.form.get('install_date'), '%Y-%m-%d').date() if request.form.get('install_date') else None
            equipment.last_maintenance_date = datetime.strptime(request.form.get('last_maintenance_date'), '%Y-%m-%d').date() if request.form.get('last_maintenance_date') else None
            equipment.next_maintenance_date = datetime.strptime(request.form.get('next_maintenance_date'), '%Y-%m-%d').date()
            equipment.client_id = request.form.get('client_id')
            equipment.user_id = assigned_user_id
            db.session.commit()
            
            url = url_for('equipment.equipment_history', equipment_id=equipment.id)
            admin_msg = f"Equipamento '{equipment.code}' atualizado por {current_user.username}."
            notify_admins(admin_msg, url, excluded_user_id=current_user.id)
            
            if int(assigned_user_id) != current_user.id:
                tech_msg = f"O equipamento '{equipment.code}' foi atualizado e está sob sua responsabilidade."
                notif_technician = Notification(user_id=int(assigned_user_id), message=tech_msg, url=url)
                db.session.add(notif_technician)
            db.session.commit()
            
            flash('Equipamento atualizado com sucesso!', 'success')
            return redirect(url_for('core.dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar equipamento: {e}', 'danger')
            
    form_data = equipment.__dict__
    return render_template('equipment_form.html', title="Editar Equipamento", clients=clients, technicians=technicians, equipment=equipment, form_data=form_data)


@equipment_bp.route('/equipment/archive/<int:equipment_id>', methods=['POST'])
@login_required
@admin_required
def toggle_archive_equipment(equipment_id):
    """Arquiva ou desarquiva um equipamento."""
    equipment = db.session.get(Equipment, equipment_id)
    if equipment:
        equipment.is_archived = not equipment.is_archived
        db.session.commit()
        flash(f'Equipamento "{equipment.code}" {"arquivado" if equipment.is_archived else "desarquivado"} com sucesso.', 'success')
    else:
        flash('Equipamento não encontrado.', 'danger')
    return redirect(request.referrer or url_for('core.dashboard'))


@equipment_bp.route('/equipments/archived')
@login_required
def archived_list():
    """Exibe a lista de equipamentos arquivados."""
    page = request.args.get('page', 1, type=int)
    per_page = 10
    if current_user.role == 'admin':
        q = Equipment.query.filter_by(is_archived=True).order_by(Equipment.next_maintenance_date.asc())
    else:
        q = Equipment.query.filter_by(user_id=current_user.id, is_archived=True).order_by(Equipment.next_maintenance_date.asc())
    equipments = q.paginate(page=page, per_page=per_page, error_out=False)
    return render_template('archived_list.html', equipments=equipments)


# --- ROTAS DE HISTÓRICO DE MANUTENÇÃO ---

@equipment_bp.route('/equipment/<int:equipment_id>/history')
@login_required
def equipment_history(equipment_id):
    """Exibe o histórico de manutenção de um equipamento específico."""
    equipment = db.session.get(Equipment, equipment_id)
    if not equipment:
        abort(404)
    if current_user.role != 'admin' and equipment.user_id != current_user.id:
        abort(403)
    history_records = equipment.maintenance_history.order_by(desc(MaintenanceHistory.maintenance_date)).all()
    return render_template('equipment_history.html', equipment=equipment, history_records=history_records)


@equipment_bp.route('/history/new/<int:equipment_id>', methods=['GET', 'POST'])
@login_required
def new_maintenance_history(equipment_id):
    """Adiciona um novo registro de manutenção para um equipamento."""
    equipment = db.session.get(Equipment, equipment_id)
    if not equipment: abort(404)
    if current_user.role != 'admin' and equipment.user_id != current_user.id: abort(403)

    if request.method == 'POST':
        try:
            maintenance_date = datetime.strptime(request.form.get('maintenance_date'), '%Y-%m-%d').date()
            cost_str = request.form.get('cost')
            labor_cost = float(cost_str.replace(',', '.')) if cost_str else 0.0

            part_ids = request.form.getlist('part_ids')
            part_quantities = request.form.getlist('part_quantities')
            total_parts_cost = 0.0
            parts_to_process = []

            for part_id, qty_str in zip(part_ids, part_quantities):
                if part_id and qty_str:
                    item = db.session.get(StockItem, int(part_id))
                    quantity_used = int(qty_str)
                    if not item or item.quantity < quantity_used:
                        raise ValueError(f'Estoque insuficiente para "{item.name}".')
                    if item.unit_cost:
                        total_parts_cost += float(item.unit_cost) * quantity_used
                    parts_to_process.append({'item': item, 'quantity': quantity_used})

            history_entry = MaintenanceHistory(
                maintenance_date=maintenance_date,
                category=request.form.get('category'),
                description=request.form.get('description'),
                equipment_id=equipment_id,
                technician_id=current_user.id,
                cost=float(labor_cost) + total_parts_cost
            )
            db.session.add(history_entry)
            db.session.flush()

            for part_data in parts_to_process:
                part_data['item'].quantity -= part_data['quantity']
                part_used_entry = MaintenancePartUsed(
                    maintenance_history_id=history_entry.id,
                    stock_item_id=part_data['item'].id,
                    quantity_used=part_data['quantity']
                )
                db.session.add(part_used_entry)

            photos = request.files.getlist('photos')
            if len(photos) > 3: raise ValueError("Você pode enviar no máximo 3 fotos.")
            for photo in photos:
                if photo and allowed_file(photo.filename):
                    ext = photo.filename.rsplit('.', 1)[1].lower()
                    filename = secure_filename(f"{uuid.uuid4()}.{ext}")
                    photo.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                    db.session.add(MaintenanceImage(filename=filename, maintenance_history_id=history_entry.id))

            equipment.last_maintenance_date = maintenance_date
            url = url_for('equipment.equipment_history', equipment_id=equipment.id)
            notify_admins(f"Nova manutenção em '{equipment.code}' por {current_user.username}.", url, current_user.id)

            db.session.commit()
            flash('Registro de manutenção e baixa de estoque realizados com sucesso!', 'success')
            return redirect(url_for('equipment.equipment_history', equipment_id=equipment_id))

        except (ValueError, TypeError) as e:
            db.session.rollback()
            flash(f'Erro nos dados: {e}. Verifique os valores.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro inesperado: {e}', 'danger')

    stock_items_from_db = StockItem.query.filter(StockItem.quantity > 0).order_by(StockItem.name).all()
    stock_items_json = [{'id': item.id, 'name': item.name, 'quantity': item.quantity} for item in stock_items_from_db]

    return render_template(
        'maintenance_form.html', equipment=equipment, categories=MAINTENANCE_CATEGORIES,
        stockItems=stock_items_json, now=datetime.utcnow()
    )

@equipment_bp.route('/history/edit/<int:history_id>', methods=['GET', 'POST'])
@login_required
def edit_maintenance(history_id):
    """Edita um registro de manutenção existente."""
    history_record = db.session.get(MaintenanceHistory, history_id)
    if not history_record:
        abort(404)
    if current_user.role != 'admin' and history_record.technician_id != current_user.id:
        abort(403)

    if request.method == 'POST':
        try:
            for part_used in history_record.parts_used:
                part_used.item.quantity += part_used.quantity_used
            MaintenancePartUsed.query.filter_by(maintenance_history_id=history_id).delete()

            maintenance_date = datetime.strptime(request.form.get('maintenance_date'), '%Y-%m-%d').date()
            labor_cost = float(request.form.get('cost', '0').replace(',', '.'))
            
            part_ids = request.form.getlist('part_ids')
            part_quantities = request.form.getlist('part_quantities')
            new_parts_cost = 0.0
            parts_to_process = []

            for part_id, qty_str in zip(part_ids, part_quantities):
                if part_id and qty_str:
                    item = db.session.get(StockItem, int(part_id))
                    quantity_used = int(qty_str)
                    if not item or item.quantity < quantity_used:
                        raise ValueError(f'Estoque insuficiente para "{item.name}".')
                    if item.unit_cost:
                        new_parts_cost += float(item.unit_cost) * quantity_used
                    parts_to_process.append({'item': item, 'quantity': quantity_used})

            history_record.maintenance_date = maintenance_date
            history_record.category = request.form.get('category')
            history_record.description = request.form.get('description')
            history_record.cost = float(labor_cost) + new_parts_cost

            for part_data in parts_to_process:
                part_data['item'].quantity -= part_data['quantity']
                new_part_used = MaintenancePartUsed(maintenance_history_id=history_id, stock_item_id=part_data['item'].id, quantity_used=part_data['quantity'])
                db.session.add(new_part_used)
            
            photos = request.files.getlist('photos')
            if len(photos) + len(history_record.images) > 3:
                raise ValueError("O total de fotos não pode exceder 3.")
            for photo in photos:
                if photo and allowed_file(photo.filename):
                    ext = photo.filename.rsplit('.', 1)[1].lower()
                    filename = secure_filename(f"{uuid.uuid4()}.{ext}")
                    photo.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                    db.session.add(MaintenanceImage(filename=filename, maintenance_history_id=history_record.id))

            db.session.commit()
            flash('Registro de manutenção atualizado com sucesso!', 'success')
            return redirect(url_for('equipment.equipment_history', equipment_id=history_record.equipment_id))

        except (ValueError, TypeError) as e:
            db.session.rollback()
            flash(f'Erro nos dados: {e}.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro inesperado: {e}', 'danger')
    
    stock_items_from_db = StockItem.query.order_by(StockItem.name).all()
    stock_items_json = [{'id': item.id, 'name': item.name, 'quantity': item.quantity} for item in stock_items_from_db]
    parts_used_json = [{'stock_item_id': part.stock_item_id, 'quantity_used': part.quantity_used} for part in history_record.parts_used]

    return render_template(
        'maintenance_form.html', title="Editar Manutenção", equipment=history_record.equipment,
        categories=MAINTENANCE_CATEGORIES, history_record=history_record,
        stockItems=stock_items_json, parts_used_json=parts_used_json, now=datetime.utcnow()
    )


@equipment_bp.route('/history/delete/<int:history_id>', methods=['POST'])
@login_required
def delete_maintenance(history_id):
    """Exclui um registro de manutenção."""
    history_record = db.session.get(MaintenanceHistory, history_id)
    if not history_record: abort(404)
    if current_user.role != 'admin' and history_record.technician_id != current_user.id: abort(403)
    
    equipment_id = history_record.equipment_id
    try:
        for part_used in history_record.parts_used:
            part_used.item.quantity += part_used.quantity_used
        
        for image in history_record.images:
            try:
                os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], image.filename))
            except OSError:
                pass # Ignora se o arquivo não existir
        
        db.session.delete(history_record)
        db.session.commit()
        flash('Registro de manutenção deletado e estoque restaurado.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao deletar registro: {e}', 'danger')
        
    return redirect(url_for('equipment.equipment_history', equipment_id=equipment_id))


@equipment_bp.route('/history/delete_photo/<int:image_id>', methods=['POST'])
@login_required
def delete_maintenance_photo(image_id):
    """Exclui uma foto de um registro de manutenção."""
    image = db.session.get(MaintenanceImage, image_id)
    if not image:
        abort(404)
    
    history_record = image.maintenance_record
    if current_user.role != 'admin' and history_record.technician_id != current_user.id:
        abort(403)
        
    try:
        os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], image.filename))
        db.session.delete(image)
        db.session.commit()
        flash('Foto removida com sucesso.', 'success')
    except OSError:
        flash('Erro ao remover o arquivo da foto, mas o registro foi limpo.', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao remover foto: {e}', 'danger')
        
    return redirect(url_for('equipment.edit_maintenance', history_id=history_record.id))


# --- ROTA PARA SERVIR IMAGENS ---

@equipment_bp.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    """Serve os arquivos de imagem que foram enviados."""
    return send_file(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))


# --- RELATÓRIO GERAL E EXPORTAÇÃO ---

@equipment_bp.route('/history/all')
@login_required
@admin_required
def full_history():
    """Exibe o relatório completo de histórico de todas as manutenções."""
    equipments = Equipment.query.options(
        joinedload(Equipment.client)
    ).order_by(Equipment.code).all()
    for eq in equipments:
        eq.loaded_history = eq.maintenance_history.options(
            joinedload(MaintenanceHistory.technician)
        ).order_by(desc(MaintenanceHistory.maintenance_date)).all()
    return render_template('full_history.html', equipments=equipments)


@equipment_bp.route('/export/maintenance')
@login_required
@admin_required
def export_maintenance():
    """Gera um arquivo Excel com o relatório completo de manutenções."""
    try:
        equipments = Equipment.query.options(joinedload(Equipment.client)).order_by(Equipment.code).all()
        data_for_df = []
        for eq in equipments:
            history_records = eq.maintenance_history.options(joinedload(MaintenanceHistory.technician)).all()
            for history in history_records:
                data_for_df.append({
                    'Data': history.maintenance_date.strftime('%d/%m/%Y'),
                    'Equipamento (Código)': eq.code,
                    'Equipamento (Modelo)': eq.model,
                    'Cliente': eq.client.name,
                    'Local': eq.location,
                    'Categoria': history.category,
                    'Técnico': history.technician.username,
                    'Custo (R$)': float(history.cost) if history.cost else 0.0,
                    'Descrição': history.description
                })

        df = pd.DataFrame(data_for_df)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Manutencoes')
        output.seek(0)

        timestamp = datetime.now(FUSO_HORARIO_SP).strftime("%Y-%m-%d")
        return send_file(
            output,
            as_attachment=True,
            download_name=f'relatorio_manutencoes_{timestamp}.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        flash(f"Erro ao gerar o relatório Excel: {e}", "danger")
        return redirect(url_for('equipment.full_history'))
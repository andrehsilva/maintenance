# app.py
import os
from datetime import datetime
from functools import wraps

import click


import io
import qrcode
from flask import send_file

from flask import (Flask, abort, flash, redirect, render_template, request,
                   url_for)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import desc, func
from sqlalchemy.orm import joinedload, subqueryload

# Importa as extensões e os modelos dos novos arquivos
from extensions import db, login_manager
from models import (Client, Equipment, MaintenanceHistory, Task, TaskAssignment,
                    User)

# --- Função de Criação da Aplicação (App Factory) ---
def create_app():
    """Cria e configura a instância da aplicação Flask."""
    app = Flask(__name__)
    
    # Configurações da Aplicação
    app.config['SECRET_KEY'] = 'uma-chave-secreta-muito-segura-e-dificil-de-adivinhar'
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'maintenance.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAINTENANCE_WARNING_DAYS'] = 15  # <-- ADICIONE AQUI

    # Inicializa as extensões com a aplicação
    db.init_app(app)
    login_manager.init_app(app)
    
    # Configura o Flask-Login
    login_manager.login_view = 'login'
    login_manager.login_message = 'Por favor, faça o login para acessar esta página.'
    login_manager.login_message_category = 'info'

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Registra as rotas e comandos com a aplicação
    register_routes(app)
    register_commands(app)
    
    return app

# --- Registro de Rotas ---
def register_routes(app):
    """Registra todas as rotas da aplicação."""
    
    MAINTENANCE_CATEGORIES = ['Manutenção Preventiva', 'Manutenção Corretiva', 'Manutenção Proativa']

    def admin_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role != 'admin':
                flash('Acesso restrito a administradores.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function

    @app.route('/')
    @app.route('/dashboard')
    @login_required
    def dashboard():
        status_filter = request.args.get('status')
        if current_user.role == 'admin':
            base_query = Equipment.query.filter_by(is_archived=False)
        else:
            base_query = Equipment.query.filter_by(user_id=current_user.id, is_archived=False)
        
        all_user_equipments = base_query.order_by(Equipment.next_maintenance_date).all()
        
        stats = {
            'total': len(all_user_equipments),
            'em_dia': len([e for e in all_user_equipments if e.status == 'Em dia']),
            'proximo': len([e for e in all_user_equipments if e.status == 'Próximo do vencimento']),
            'vencido': len([e for e in all_user_equipments if e.status == 'Vencido'])
        }

        equipments_to_display = all_user_equipments
        if status_filter == 'em_dia':
            equipments_to_display = [e for e in all_user_equipments if e.status == 'Em dia']
        elif status_filter == 'proximo':
            equipments_to_display = [e for e in all_user_equipments if e.status == 'Próximo do vencimento']
        elif status_filter == 'vencido':
            equipments_to_display = [e for e in all_user_equipments if e.status == 'Vencido']
        
        return render_template('dashboard.html', equipments=equipments_to_display, stats=stats, active_filter=status_filter)
    
    # Em app.py, dentro da função register_routes(app)

    # --- ROTA DE CONFIGURAÇÕES ---
    @app.route('/settings', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def manage_settings():
        if request.method == 'POST':
            try:
                # Pega o novo valor do formulário e valida se é um número inteiro
                new_days_str = request.form.get('warning_days')
                new_days_int = int(new_days_str)

                # Busca a configuração no banco de dados
                setting = db.session.get(Setting, 'maintenance_warning_days')
                
                if setting:
                    # Se já existe, atualiza o valor
                    setting.value = str(new_days_int)
                else:
                    # Se não existe, cria uma nova
                    setting = Setting(key='maintenance_warning_days', value=str(new_days_int))
                    db.session.add(setting)
                
                db.session.commit()
                flash('Configurações salvas com sucesso!', 'success')

            except (ValueError, TypeError):
                flash('O valor informado deve ser um número inteiro.', 'danger')
            
            return redirect(url_for('manage_settings'))

        # Para requisições GET, busca o valor atual para exibir no formulário
        setting = db.session.get(Setting, 'maintenance_warning_days')
        current_days = setting.value if setting else '15' # Padrão de 15 dias se não estiver no DB

        return render_template('settings.html', warning_days=current_days)

    # --- Rotas de Autenticação ---
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            user = User.query.filter_by(username=request.form.get('username')).first()
            if user and user.check_password(request.form.get('password')):
                login_user(user)
                return redirect(url_for('dashboard'))
            else:
                flash('Usuário ou senha inválidos.', 'danger')
        return render_template('login.html')

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            with app.app_context():
                if User.query.filter_by(username=username).first():
                    flash('Este nome de usuário já existe.', 'warning')
                    return redirect(url_for('register'))
                role = 'admin' if User.query.count() == 0 else 'technician'
            new_user = User(username=username, role=role)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash(f'Conta criada como {role}. Faça o login.', 'success')
            return redirect(url_for('login'))
        return render_template('register.html')

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('Você saiu do sistema.', 'success')
        return redirect(url_for('login'))

    # --- Rotas de Gerenciamento de Equipamentos ---
    @app.route('/equipment/new', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def new_equipment():
        clients = Client.query.order_by(Client.name).all()
        technicians = User.query.filter_by(role='technician').order_by(User.username).all()
        if not clients:
            flash('Você precisa cadastrar um cliente antes de adicionar um equipamento.', 'warning')
            return redirect(url_for('new_client'))
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
                    code=code, model=request.form.get('model'), location=request.form.get('location'),
                    description=request.form.get('description'),
                    install_date=datetime.strptime(request.form.get('install_date'), '%Y-%m-%d').date() if request.form.get('install_date') else None,
                    last_maintenance_date=datetime.strptime(request.form.get('last_maintenance_date'), '%Y-%m-%d').date() if request.form.get('last_maintenance_date') else None,
                    next_maintenance_date=datetime.strptime(request.form.get('next_maintenance_date'), '%Y-%m-%d').date(),
                    user_id=assigned_user_id, client_id=request.form.get('client_id')
                )
                db.session.add(equipment)
                db.session.commit()
                flash('Equipamento cadastrado com sucesso!', 'success')
                return redirect(url_for('dashboard'))
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao cadastrar equipamento: {e}', 'danger')
        return render_template('equipment_form.html', title="Cadastrar Novo Equipamento", clients=clients, technicians=technicians, equipment=None, form_data={})

    @app.route('/equipment/edit/<int:equipment_id>', methods=['GET', 'POST'])
    @admin_required
    @login_required
    def edit_equipment(equipment_id):
        equipment = db.session.get(Equipment, equipment_id)
        if not equipment:
            abort(404)
        clients = Client.query.order_by(Client.name).all()
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
                flash('Equipamento atualizado com sucesso!', 'success')
                return redirect(url_for('dashboard'))
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao atualizar equipamento: {e}', 'danger')
        form_data = equipment.__dict__
        return render_template('equipment_form.html', title="Editar Equipamento", clients=clients, technicians=technicians, equipment=equipment, form_data=form_data)

    @app.route('/equipment/archive/<int:equipment_id>', methods=['POST'])
    @login_required
    @admin_required
    def toggle_archive_equipment(equipment_id):
        equipment = db.session.get(Equipment, equipment_id)
        if equipment:
            equipment.is_archived = not equipment.is_archived
            db.session.commit()
            flash(f'Equipamento "{equipment.code}" {"arquivado" if equipment.is_archived else "desarquivado"} com sucesso.', 'success')
        else:
            flash('Equipamento não encontrado.', 'danger')
        if 'archived_list' in request.referrer:
            return redirect(url_for('archived_list'))
        return redirect(url_for('dashboard'))

    @app.route('/archived')
    @login_required
    @admin_required
    def archived_list():
        archived_equipments = Equipment.query.filter_by(is_archived=True).order_by(Equipment.code).all()
        return render_template('archived_list.html', equipments=archived_equipments)

    # --- Rotas de Histórico de Manutenção ---
    @app.route('/equipment/<int:equipment_id>/history')
    @login_required
    def equipment_history(equipment_id):
        equipment = db.session.get(Equipment, equipment_id)
        if not equipment:
            abort(404)
        if current_user.role != 'admin' and equipment.user_id != current_user.id:
            abort(403)
        history_records = equipment.maintenance_history.all()
        return render_template('equipment_history.html', equipment=equipment, history_records=history_records)

    @app.route('/history/new/<int:equipment_id>', methods=['GET', 'POST'])
    @login_required
    def new_maintenance_history(equipment_id):
        equipment = db.session.get(Equipment, equipment_id)
        if not equipment:
            abort(404)
        if current_user.role != 'admin' and equipment.user_id != current_user.id:
            abort(403)
        if request.method == 'POST':
            try:
                maintenance_date = datetime.strptime(request.form.get('maintenance_date'), '%Y-%m-%d').date()
                cost_str = request.form.get('cost')
                cost = float(cost_str.replace(',', '.')) if cost_str else None
                
                history_entry = MaintenanceHistory(
                    maintenance_date=maintenance_date, category=request.form.get('category'),
                    description=request.form.get('description'), equipment_id=equipment_id,
                    technician_id=current_user.id,
                    cost=cost
                )
                equipment.last_maintenance_date = maintenance_date
                db.session.add(history_entry)
                db.session.commit()
                flash('Registro de manutenção adicionado com sucesso!', 'success')
                return redirect(url_for('equipment_history', equipment_id=equipment_id))
            except (ValueError, TypeError):
                flash('Valor de custo inválido. Use um formato como 150.50.', 'danger')
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao adicionar registro: {e}', 'danger')
        return render_template('maintenance_form.html', equipment=equipment, categories=MAINTENANCE_CATEGORIES, now=datetime.utcnow())

    @app.route('/history/edit/<int:history_id>', methods=['GET', 'POST'])
    @login_required
    def edit_maintenance(history_id):
        history_record = db.session.get(MaintenanceHistory, history_id)
        if not history_record:
            abort(404)
        if current_user.role != 'admin' and history_record.technician_id != current_user.id:
            abort(403)
        if request.method == 'POST':
            try:
                history_record.maintenance_date = datetime.strptime(request.form.get('maintenance_date'), '%Y-%m-%d').date()
                history_record.category = request.form.get('category')
                history_record.description = request.form.get('description')
                cost_str = request.form.get('cost')
                history_record.cost = float(cost_str.replace(',', '.')) if cost_str else None
                db.session.commit()
                flash('Registro de manutenção atualizado com sucesso!', 'success')
                return redirect(url_for('equipment_history', equipment_id=history_record.equipment_id))
            except (ValueError, TypeError):
                flash('Valor de custo inválido. Use um formato como 150.50.', 'danger')
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao atualizar registro: {e}', 'danger')
        return render_template('maintenance_form.html', title="Editar Manutenção", equipment=history_record.equipment, categories=MAINTENANCE_CATEGORIES, history_record=history_record)

    @app.route('/history/delete/<int:history_id>', methods=['POST'])
    @login_required
    def delete_maintenance(history_id):
        history_record = db.session.get(MaintenanceHistory, history_id)
        if not history_record:
            abort(404)
        if current_user.role != 'admin' and history_record.technician_id != current_user.id:
            abort(403)
        equipment_id = history_record.equipment_id
        try:
            db.session.delete(history_record)
            db.session.commit()
            flash('Registro de manutenção deletado com sucesso.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao deletar registro: {e}', 'danger')
        return redirect(url_for('equipment_history', equipment_id=equipment_id))


    @app.route('/history/all')
    @login_required
    @admin_required
    def full_history():
        equipments = Equipment.query.options(
            joinedload(Equipment.client)
        ).order_by(Equipment.code).all()
        for eq in equipments:
            eq.loaded_history = eq.maintenance_history.options(
                joinedload(MaintenanceHistory.technician)
            ).all()
        return render_template('full_history.html', equipments=equipments)
    

    # --- Rotas de Gerenciamento de Clientes ---
    @app.route('/clients')
    @login_required
    @admin_required
    def client_list():
        clients = Client.query.order_by(Client.name).all()
        return render_template('client_list.html', clients=clients)

    @app.route('/client/new', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def new_client():
        if request.method == 'POST':
            name = request.form.get('name')
            if Client.query.filter_by(name=name).first():
                flash('Já existe um cliente com este nome.', 'warning')
            else:
                client = Client(
                    name=name, address=request.form.get('address'),
                    contact_person=request.form.get('contact_person'),
                    phone=request.form.get('phone')
                )
                db.session.add(client)
                db.session.commit()
                flash('Cliente cadastrado com sucesso!', 'success')
                return redirect(url_for('client_list'))
        return render_template('client_form.html', title="Novo Cliente", client=None)

    @app.route('/client/edit/<int:client_id>', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def edit_client(client_id):
        client = db.session.get(Client, client_id)
        if not client:
            abort(404)
        if request.method == 'POST':
            client.name, client.address = request.form.get('name'), request.form.get('address')
            client.contact_person, client.phone = request.form.get('contact_person'), request.form.get('phone')
            db.session.commit()
            flash('Cliente atualizado com sucesso!', 'success')
            return redirect(url_for('client_list'))
        return render_template('client_form.html', title="Editar Cliente", client=client)

    @app.route('/client/delete/<int:client_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_client(client_id):
        client = db.session.get(Client, client_id)
        if client:
            if client.equipments:
                flash('Não é possível deletar um cliente que possui equipamentos associados.', 'danger')
            else:
                db.session.delete(client)
                db.session.commit()
                flash('Cliente deletado com sucesso!', 'success')
        return redirect(url_for('client_list'))

    # --- Rotas de Gerenciamento de Tarefas ---
    @app.route('/tasks')
    @login_required
    def technician_tasks():
        assignments = TaskAssignment.query.join(Task).filter(
            TaskAssignment.user_id == current_user.id
        ).order_by(desc(Task.created_date)).all()
        return render_template('technician_tasks.html', assignments=assignments)

    @app.route('/tasks/admin')
    @login_required
    @admin_required
    def admin_tasks():
        tasks = Task.query.order_by(desc(Task.created_date)).all()
        return render_template('admin_tasks.html', tasks=tasks)

    @app.route('/tasks/new', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def create_task():
        technicians = User.query.filter_by(role='technician').order_by(User.username).all()
        if request.method == 'POST':
            title = request.form.get('title')
            description = request.form.get('description')
            technician_ids = request.form.getlist('technician_ids')
            if not title or not technician_ids:
                flash('Título e ao menos um técnico são obrigatórios.', 'danger')
                return render_template('task_form.html', technicians=technicians, task=None)
            try:
                new_task = Task(title=title, description=description, creator_id=current_user.id)
                db.session.add(new_task)
                db.session.flush()
                for tech_id in technician_ids:
                    assignment = TaskAssignment(task_id=new_task.id, user_id=int(tech_id))
                    db.session.add(assignment)
                db.session.commit()
                flash('Tarefa criada e atribuída com sucesso!', 'success')
                return redirect(url_for('admin_tasks'))
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao criar tarefa: {e}', 'danger')
        return render_template('task_form.html', technicians=technicians, task=None)
    
    @app.route('/tasks/edit/<int:task_id>', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def edit_task(task_id):
        task = db.session.get(Task, task_id)
        if not task:
            abort(404)
        technicians = User.query.filter_by(role='technician').order_by(User.username).all()
        if request.method == 'POST':
            title = request.form.get('title')
            description = request.form.get('description')
            new_technician_ids = {int(i) for i in request.form.getlist('technician_ids')}
            if not title or not new_technician_ids:
                flash('Título e ao menos um técnico são obrigatórios.', 'danger')
                return render_template('task_form.html', technicians=technicians, task=task)
            try:
                task.title = title
                task.description = description
                current_technician_ids = {a.user_id for a in task.assignments}
                ids_to_remove = current_technician_ids - new_technician_ids
                if ids_to_remove:
                    TaskAssignment.query.filter(TaskAssignment.task_id == task_id, TaskAssignment.user_id.in_(ids_to_remove)).delete(synchronize_session=False)
                ids_to_add = new_technician_ids - current_technician_ids
                for tech_id in ids_to_add:
                    new_assignment = TaskAssignment(task_id=task_id, user_id=tech_id)
                    db.session.add(new_assignment)
                db.session.commit()
                flash('Tarefa atualizada com sucesso!', 'success')
                return redirect(url_for('admin_tasks'))
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao atualizar tarefa: {e}', 'danger')
        assigned_technician_ids = [a.user_id for a in task.assignments]
        return render_template('task_form.html', title="Editar Tarefa", task=task, technicians=technicians, assigned_technician_ids=assigned_technician_ids)
    
    @app.route('/tasks/delete/<int:task_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_task(task_id):
        task = db.session.get(Task, task_id)
        if not task:
            abort(404)
        try:
            db.session.delete(task)
            db.session.commit()
            flash('Tarefa deletada com sucesso.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao deletar tarefa: {e}', 'danger')
        return redirect(url_for('admin_tasks'))

    @app.route('/tasks/update_status/<int:assignment_id>', methods=['POST'])
    @login_required
    def update_task_status(assignment_id):
        new_status = request.form.get('status')
        assignment = db.session.get(TaskAssignment, assignment_id)
        if not assignment:
            abort(404)
        if assignment.user_id != current_user.id and current_user.role != 'admin':
            abort(403)
        try:
            assignment.status = new_status
            db.session.commit()
            flash('Status da tarefa atualizado.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar status: {e}', 'danger')
        return redirect(url_for('technician_tasks'))
    
    # --- Rotas de QR Code ---
    @app.route('/public/equipment/<code>')
    def public_summary(code):
        equipment = Equipment.query.filter_by(code=code).first()
        if not equipment or equipment.is_archived:
            return render_template('public_summary_not_found.html'), 404
        history_records = equipment.maintenance_history.all()
        return render_template('public_summary.html', equipment=equipment, history_records=history_records)
    
    @app.route('/equipment/<code>/qrcode')
    @login_required
    @admin_required
    def display_qrcode(code):
        equipment = Equipment.query.filter_by(code=code).first()
        if not equipment:
            abort(404)
        return render_template('qrcode_display.html', equipment=equipment)
    
    @app.route('/equipment/<code>/qrcode_image')
    def qrcode_image(code):
        public_url = url_for('public_summary', code=code, _external=True)
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(public_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img_io = io.BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)
        return send_file(img_io, mimetype='image/png')
    
    # --- NOVA ROTA: Relatório Financeiro ---
    @app.route('/reports/financial')
    @login_required
    @admin_required
    def financial_report():
        clients = Client.query.order_by(Client.name).all()
        client_id = request.args.get('client_id', type=int)
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        query = db.session.query(MaintenanceHistory).join(Equipment)
        
        if client_id:
            query = query.filter(Equipment.client_id == client_id)
        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            query = query.filter(MaintenanceHistory.maintenance_date >= start_date)
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            query = query.filter(MaintenanceHistory.maintenance_date <= end_date)
            
        records = query.order_by(desc(MaintenanceHistory.maintenance_date)).all()
        
        total_cost = sum(record.cost for record in records if record.cost is not None)

        return render_template('financial_report.html', 
                               clients=clients, 
                               records=records,
                               total_cost=total_cost,
                               filters=request.args)

# --- Registro de Comandos CLI ---
def register_commands(app):
    """Registra comandos CLI para a aplicação."""
    @app.cli.command("init-db")
    def init_db_command():
        """Limpa os dados existentes e cria novas tabelas."""
        with app.app_context():
            db.drop_all()
            db.create_all()
            click.echo("Banco de dados inicializado com sucesso.")

# --- Instância da Aplicação ---
app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
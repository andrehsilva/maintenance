# app.py
import os
from datetime import datetime
from functools import wraps

import click

import io
import re
import qrcode
import uuid
from werkzeug.utils import secure_filename
from flask import send_file
from datetime import date
from flask import (Flask, abort, flash, redirect, render_template, request, url_for)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import desc, func
from sqlalchemy.orm import joinedload, subqueryload
from math import ceil

# Importa as extensões e os modelos dos novos arquivos
from extensions import db, login_manager
from models import (Client, Equipment, MaintenanceHistory, Task, TaskAssignment, User, Setting, Notification, MaintenanceImage)

# --- Configurações de Upload ---
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Função de Criação da Aplicação (App Factory) ---
def create_app():
    """Cria e configura a instância da aplicação Flask."""
    app = Flask(__name__)
    
    # Configurações da Aplicação
    app.config['SECRET_KEY'] = 'D8C73C7FF3F7D86734D7E319EFB5C'
    basedir = os.path.abspath(os.path.dirname(__file__))
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url.replace("postgres://", "postgresql://", 1)
    else:
        basedir = os.path.abspath(os.path.dirname(__file__))
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'maintenance.db')


    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAINTENANCE_WARNING_DAYS'] = 15  # <-- ADICIONE AQUI
    
    # --- INÍCIO DA CORREÇÃO ---
    # Define a pasta de uploads na configuração do Flask
    app.config['UPLOAD_FOLDER'] = os.path.join(basedir, UPLOAD_FOLDER)
    # Define um tamanho máximo para os arquivos (ex: 16MB)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

    # GARANTE QUE A PASTA DE UPLOADS EXISTA
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    # --- FIM DA CORREÇÃO ---




    # Inicializa as extensões com a aplicação
    db.init_app(app)
    login_manager.init_app(app)
    
    # Configura o Flask-Login
    login_manager.login_view = 'login'
    login_manager.login_message = 'Por favor, faça o login para acessar esta página.'
    login_manager.login_message_category = 'info'

    @app.context_processor
    def inject_notifications():
        if current_user.is_authenticated:
            unread_notifications_count = current_user.notifications.filter_by(is_read=False).count()
            recent_notifications = current_user.notifications.order_by(desc(Notification.timestamp)).limit(5).all()
            return dict(
                unread_notifications_count=unread_notifications_count,
                recent_notifications=recent_notifications
            )
        return dict(unread_notifications_count=0, recent_notifications=[])

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

    # Em app.py, dentro de register_routes(app)
    MAINTENANCE_CATEGORIES = ['Manutenção Preventiva', 'Manutenção Corretiva', 'Manutenção Proativa']

    def notify_admins(message, url, excluded_user_id=None):
        """Cria uma notificação para todos os administradores."""
        admins = User.query.filter_by(role='admin').all()
        for admin in admins:
            if admin.id != excluded_user_id:
                notif = Notification(user_id=admin.id, message=message, url=url)
                db.session.add(notif)

    def admin_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role != 'admin':
                flash('Acesso restrito a administradores.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function

    # --- ROTAS DE GERENCIAMENTO DE USUÁRIOS (ADMIN) ---
    @app.route('/users')
    @login_required
    @admin_required
    def user_list():
        """Exibe uma lista de todos os usuários."""
        users = User.query.order_by(User.username).all()
        return render_template('user_list.html', users=users)

    @app.route('/user/new', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def create_user():
        """Cria um novo usuário (admin ou técnico)."""
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            role = request.form.get('role')

            if not username or not password or not role:
                flash('Todos os campos são obrigatórios.', 'danger')
                return render_template('user_form.html', title="Criar Novo Usuário", user=None)

            if User.query.filter_by(username=username).first():
                flash('Este nome de usuário já está em uso.', 'warning')
                return render_template('user_form.html', title="Criar Novo Usuário", user=None, form_data=request.form)
            
            new_user = User(username=username, role=role)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash(f'Usuário "{username}" criado com sucesso!', 'success')
            return redirect(url_for('user_list'))
            
        return render_template('user_form.html', title="Criar Novo Usuário", user=None, form_data={})

    @app.route('/user/edit/<int:user_id>', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def edit_user(user_id):
        user = db.session.get(User, user_id)
        if not user:
            abort(404)
            
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password') # Senha é opcional na edição
            role = request.form.get('role')

            # Verifica se o novo username já está em uso por outro usuário
            existing_user = User.query.filter(User.username == username, User.id != user_id).first()
            if existing_user:
                flash('Este nome de usuário já está em uso por outra conta.', 'warning')
                return render_template('user_form.html', title="Editar Usuário", user=user, form_data=request.form)

            user.username = username
            user.role = role
            # Só atualiza a senha se uma nova for fornecida
            if password:
                user.set_password(password)
            
            db.session.commit()
            flash(f'Usuário "{username}" atualizado com sucesso!', 'success')
            return redirect(url_for('user_list'))

        return render_template('user_form.html', title="Editar Usuário", user=user, form_data=user.__dict__)

    @app.route('/user/delete/<int:user_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_user(user_id):
        user_to_delete = db.session.get(User, user_id)
        if not user_to_delete:
            flash('Usuário não encontrado.', 'danger')
            return redirect(url_for('user_list'))
        
        # Impede que o admin se auto-delete
        if user_to_delete.id == current_user.id:
            flash('Você não pode excluir sua própria conta.', 'danger')
            return redirect(url_for('user_list'))
            
        # Impede a exclusão se houver itens associados (exemplo com equipamentos)
        if user_to_delete.equipments:
             flash(f'Não é possível excluir o usuário "{user_to_delete.username}", pois ele está associado a equipamentos.', 'danger')
             return redirect(url_for('user_list'))

        db.session.delete(user_to_delete)
        db.session.commit()
        flash(f'Usuário "{user_to_delete.username}" excluído com sucesso.', 'success')
        return redirect(url_for('user_list'))
    
    

    @app.route('/')
    @app.route('/dashboard')
    @login_required
    def dashboard():
        status_filter = request.args.get('status')
        page = request.args.get('page', 1, type=int)
        per_page = 10

        # Base query depende do perfil
        if current_user.role == 'admin':
            base_query = Equipment.query.filter_by(is_archived=False)
        else:
            base_query = Equipment.query.filter_by(user_id=current_user.id, is_archived=False)

        # Pegamos todos os equipamentos para calcular os stats
        all_user_equipments = base_query.order_by(Equipment.next_maintenance_date).all()

        stats = {
            'total': len(all_user_equipments),
            'em_dia': len([e for e in all_user_equipments if e.status == 'Em dia']),
            'proximo': len([e for e in all_user_equipments if e.status == 'Próximo do vencimento']),
            'vencido': len([e for e in all_user_equipments if e.status == 'Vencido'])
        }

        # Filtro por status
        equipments_to_display = all_user_equipments
        if status_filter == 'em_dia':
            equipments_to_display = [e for e in all_user_equipments if e.status == 'Em dia']
        elif status_filter == 'proximo':
            equipments_to_display = [e for e in all_user_equipments if e.status == 'Próximo do vencimento']
        elif status_filter == 'vencido':
            equipments_to_display = [e for e in all_user_equipments if e.status == 'Vencido']

        # ---- Paginação manual (quando temos uma lista e não um query.paginate) ----
        total_items = len(equipments_to_display)
        total_pages = ceil(total_items / per_page)

        start = (page - 1) * per_page
        end = start + per_page
        items = equipments_to_display[start:end]

        # Criamos um objeto "fake" parecido com Pagination
        class Pagination:
            def __init__(self, items, page, per_page, total):
                self.items = items
                self.page = page
                self.per_page = per_page
                self.total = total
                self.pages = ceil(total / per_page)
                self.has_prev = page > 1
                self.has_next = page < self.pages
                self.prev_num = page - 1
                self.next_num = page + 1

        equipments = Pagination(items, page, per_page, total_items)

        return render_template(
            'dashboard.html',
            equipments=equipments,
            stats=stats,
            active_filter=status_filter
        )

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
    # Em app.py

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            user = User.query.filter_by(username=request.form.get('username')).first()

            if user and user.check_password(request.form.get('password')):
                # VERIFICAÇÃO ADICIONAL: O usuário está ativo?
                if not user.is_active:
                    flash('Sua conta ainda não foi aprovada por um administrador.', 'warning')
                    return redirect(url_for('login'))

                login_user(user)
                return redirect(url_for('dashboard'))
            else:
                flash('Usuário ou senha inválidos.', 'danger')

        return render_template('login.html')

    # Em app.py

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')

            if User.query.filter_by(username=username).first():
                flash('Este nome de usuário já existe.', 'warning')
                return redirect(url_for('register'))

            # O primeiro usuário é admin E ativo. Os demais começam inativos.
            is_first_user = User.query.count() == 0
            role = 'admin' if is_first_user else 'technician'

            new_user = User(username=username, role=role, is_active=is_first_user)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()

            if is_first_user:
                flash('Conta de administrador criada com sucesso! Faça o login.', 'success')
            else:
                # Notifica os admins sobre o novo registro pendente
                msg = f"Novo usuário '{username}' se registrou e aguarda aprovação."
                notify_admins(msg, url_for('user_list'))
                db.session.commit()
                flash('Conta criada com sucesso! Aguardando aprovação do administrador.', 'info')

            return redirect(url_for('login'))

        return render_template('register.html')


    # Em app.py, adicione esta nova rota junto com as outras de gerenciamento de usuários

    @app.route('/user/approve/<int:user_id>', methods=['POST'])
    @login_required
    @admin_required
    def approve_user(user_id):
        user_to_approve = db.session.get(User, user_id)
        if user_to_approve:
            user_to_approve.is_active = True
            
            # Notifica o usuário que sua conta foi aprovada
            msg = "Sua conta foi aprovada! Agora você já pode fazer o login no sistema."
            user_notif = Notification(user_id=user_to_approve.id, message=msg, url=url_for('login'))
            db.session.add(user_notif)
            
            db.session.commit()
            flash(f'Usuário "{user_to_approve.username}" aprovado com sucesso.', 'success')
        else:
            flash('Usuário não encontrado.', 'danger')
            
        return redirect(url_for('user_list'))



    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('Você saiu do sistema.', 'success')
        return redirect(url_for('login'))

    # --- Rotas de Gerenciamento de Equipamentos ---
    # Lista de equipamentos ativos
    @app.route('/equipments')
    @login_required
    def equipment_list():
        page = request.args.get('page', 1, type=int)
        per_page = 10

        if current_user.role == 'admin':
            q = Equipment.query.filter_by(is_archived=False).order_by(Equipment.next_maintenance_date.asc())
        else:
            q = Equipment.query.filter_by(user_id=current_user.id, is_archived=False).order_by(Equipment.next_maintenance_date.asc())

        equipments = q.paginate(page=page, per_page=per_page, error_out=False)

        return render_template('equipment_list.html', equipments=equipments)



    @app.route('/equipment/new', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def new_equipment():
        clients = Client.query.filter_by(is_archived=False).order_by(Client.name).all()
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

                # Lógica de Notificação (Já estava correta, mantida aqui)
                admins = User.query.filter_by(role='admin').all()
                for admin in admins:
                    if admin.id != current_user.id:
                        notif = Notification(user_id=admin.id, message=f"Novo equipamento '{equipment.code}' foi cadastrado por {current_user.username}.", url=url_for('equipment_history', equipment_id=equipment.id))
                        db.session.add(notif)
                if int(assigned_user_id) != current_user.id:
                    notif_technician = Notification(user_id=int(assigned_user_id), message=f"O equipamento '{equipment.code}' foi atribuído a você.", url=url_for('equipment_history', equipment_id=equipment.id))
                    db.session.add(notif_technician)
                db.session.commit()

                flash('Equipamento cadastrado com sucesso!', 'success')
                return redirect(url_for('dashboard'))

            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao cadastrar equipamento: {e}', 'danger')
                return render_template('equipment_form.html', title="Cadastrar Equipamento", clients=clients, technicians=technicians, equipment=None, form_data=request.form)

        # Lógica para GET (agora sem duplicação)
        today_date = date.today().strftime('%Y-%m-%d')
        form_data = {'install_date': today_date}
        return render_template('equipment_form.html', title="Cadastrar Novo Equipamento", clients=clients, technicians=technicians, equipment=None, form_data=form_data)


    @app.route('/equipment/edit/<int:equipment_id>', methods=['GET', 'POST'])
    @admin_required
    @login_required
    def edit_equipment(equipment_id):
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
                admin_msg = f"Equipamento '{equipment.code}' atualizado por {current_user.username}."
                admins = User.query.filter_by(role='admin').all()
                for admin in admins:
                    if admin.id != current_user.id:
                        notif = Notification(user_id=admin.id, message=admin_msg, url=url_for('equipment_history', equipment_id=equipment.id))
                        db.session.add(notif)
                if int(assigned_user_id) != current_user.id:
                    tech_msg = f"O equipamento '{equipment.code}' foi atualizado e está sob sua responsabilidade."
                    notif_technician = Notification(user_id=int(assigned_user_id), message=tech_msg, url=url_for('equipment_history', equipment_id=equipment.id))
                    db.session.add(notif_technician)
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

        # Redireciona de volta para a página de onde o usuário veio
        # (Funciona para a lista de arquivados e para a nova lista de equipamentos)
        return redirect(request.referrer or url_for('dashboard'))

    # Lista de equipamentos arquivados
    @app.route('/equipments/archived')
    @login_required
    def archived_list():
        page = request.args.get('page', 1, type=int)
        per_page = 10

        if current_user.role == 'admin':
            q = Equipment.query.filter_by(is_archived=True).order_by(Equipment.next_maintenance_date.asc())
        else:
            q = Equipment.query.filter_by(user_id=current_user.id, is_archived=True).order_by(Equipment.next_maintenance_date.asc())

        equipments = q.paginate(page=page, per_page=per_page, error_out=False)

        return render_template('archived_list.html', equipments=equipments)

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

    # Em app.py

    # --- NOVA ROTA PARA SERVIR IMAGENS ---
    @app.route('/uploads/<filename>')
    @login_required
    def uploaded_file(filename):
        return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    

    # Função reescrita:
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
                # --- Cria o registro de manutenção primeiro ---
                maintenance_date = datetime.strptime(request.form.get('maintenance_date'), '%Y-%m-%d').date()
                cost_str = request.form.get('cost')
                cost = float(cost_str.replace(',', '.')) if cost_str else None
                
                history_entry = MaintenanceHistory(
                    maintenance_date=maintenance_date, 
                    category=request.form.get('category'),
                    description=request.form.get('description'), 
                    equipment_id=equipment_id,
                    technician_id=current_user.id,
                    cost=cost
                )
                db.session.add(history_entry)
                # Usamos flush para obter o ID do history_entry antes do commit final
                db.session.flush()
    
                # --- INÍCIO DA LÓGICA DE UPLOAD DE IMAGENS ---
                photos = request.files.getlist('photos')
                if len(photos) > 3:
                    flash('Você pode enviar no máximo 3 fotos.', 'danger')
                    # Damos rollback para não salvar o registro de manutenção se as fotos falharem
                    db.session.rollback()
                    return redirect(request.url)
    
                for photo in photos:
                    # Verifica se um arquivo foi realmente enviado e se a extensão é permitida
                    if photo and allowed_file(photo.filename):
                        ext = photo.filename.rsplit('.', 1)[1].lower()
                        # Cria um nome de arquivo único para evitar sobrescrever arquivos
                        filename = secure_filename(f"{uuid.uuid4()}.{ext}")
                        photo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                        
                        # Cria o registro da imagem no banco de dados
                        new_image = MaintenanceImage(filename=filename, maintenance_history_id=history_entry.id)
                        db.session.add(new_image)
                # --- FIM DA LÓGICA DE UPLOAD ---
    
                # Atualiza a data da última manutenção no equipamento
                equipment.last_maintenance_date = maintenance_date
                
                # --- LÓGICA DE NOTIFICAÇÃO ---
                admin_msg = f"Nova manutenção em '{equipment.code}' registrada por {current_user.username}."
                notify_admins(admin_msg, url_for('equipment_history', equipment_id=equipment.id), excluded_user_id=current_user.id)
                
                if equipment.user_id != current_user.id:
                    tech_msg = f"Uma nova manutenção foi registrada no equipamento '{equipment.code}'."
                    tech_notif = Notification(user_id=equipment.user_id, message=tech_msg, url=url_for('equipment_history', equipment_id=equipment.id))
                    db.session.add(tech_notif)
                
                # Agora faz o commit de tudo (manutenção, imagens e notificações)
                db.session.commit()
                
                flash('Registro de manutenção adicionado com sucesso!', 'success')
                return redirect(url_for('equipment_history', equipment_id=equipment_id))
                
            except (ValueError, TypeError):
                db.session.rollback()
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
                admin_msg = f"Registro de manutenção em '{history_record.equipment.code}' foi atualizado por {current_user.username}."
                admins = User.query.filter_by(role='admin').all()
                for admin in admins:
                    if admin.id != current_user.id:
                        notif = Notification(user_id=admin.id, message=admin_msg, url=url_for('equipment_history', equipment_id=history_record.equipment.id))
                        db.session.add(notif)
                if history_record.equipment.user_id != current_user.id:
                    tech_msg = f"O registro de manutenção do equipamento '{history_record.equipment.code}' foi atualizado."
                    notif_technician = Notification(user_id=history_record.equipment.user_id, message=tech_msg, url=url_for('equipment_history', equipment_id=history_record.equipment.id))
                    db.session.add(notif_technician)
                db.session.commit()
                flash('Registro de manutenção atualizado com sucesso!', 'success')
                return redirect(url_for('equipment_history', equipment_id=history_record.equipment_id))
            except (ValueError, TypeError):
                flash('Valor de custo inválido. Use um formato como 150.50.', 'danger')
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao atualizar registro: {e}', 'danger')
        return render_template('maintenance_form.html', title="Editar Manutenção", equipment=history_record.equipment, categories=MAINTENANCE_CATEGORIES, history_record=history_record)

    # Em app.py

    @app.route('/history/delete/<int:history_id>', methods=['POST'])
    @login_required
    def delete_maintenance(history_id):
        history_record = db.session.get(MaintenanceHistory, history_id)
        if not history_record:
            abort(404)
        if current_user.role != 'admin' and history_record.technician_id != current_user.id:
            abort(403)
    
        try:
            # --- INÍCIO DA CORREÇÃO ---
            # 1. Pegue todas as informações ANTES de deletar
            equipment_id = history_record.equipment_id
            equipment_code = history_record.equipment.code
            technician_id = history_record.equipment.user_id
            image_filenames = [image.filename for image in history_record.images]
            # --- FIM DA CORREÇÃO ---
    
            # 2. Delete os arquivos físicos das imagens da pasta 'uploads'
            for filename in image_filenames:
                try:
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                except OSError:
                    # Ignora o erro se o arquivo não for encontrado
                    pass
                
            # 3. Delete o registro do banco de dados (o cascade deleta as referências das imagens)
            db.session.delete(history_record)
            db.session.commit()
    
            # 4. Crie as notificações usando as informações salvas
            admin_msg = f"Um registro de manutenção do equipamento '{equipment_code}' foi deletado por {current_user.username}."
            notify_admins(admin_msg, url_for('equipment_history', equipment_id=equipment_id), excluded_user_id=current_user.id)
            
            if technician_id != current_user.id:
                tech_msg = f"Um registro de manutenção do equipamento '{equipment_code}' foi deletado."
                notif_technician = Notification(user_id=technician_id, message=tech_msg, url=url_for('equipment_history', equipment_id=equipment_id))
                db.session.add(notif_technician)
            
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
            # ADICIONE A ORDENAÇÃO AQUI
            eq.loaded_history = eq.maintenance_history.options(
                joinedload(MaintenanceHistory.technician)
            ).order_by(desc(MaintenanceHistory.maintenance_date)).all()
        return render_template('full_history.html', equipments=equipments)
    

    # --- Rotas de Gerenciamento de Clientes ---
    @app.route('/clients')
    @login_required
    @admin_required
    def client_list():
        # ALTERADO: Adicionado filtro .filter_by(is_archived=False)
        clients = Client.query.filter_by(is_archived=False).order_by(Client.name).all()
        return render_template('client_list.html', clients=clients)


    # Em app.py
    @app.route('/client/new', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def new_client():
        if request.method == 'POST':
            name = request.form.get('name')
            phone = request.form.get('phone')

            # --- INÍCIO DA VALIDAÇÃO ---
            if phone: # Apenas valida se um telefone foi digitado
                # Limpa o telefone, deixando apenas os números
                cleaned_phone = re.sub(r'\D', '', phone)
                # Verifica se tem 10 ou 11 dígitos
                if not re.match(r'^\d{10,11}$', cleaned_phone):
                    flash('O número de telefone informado é inválido.', 'danger')
                    # Retorna o formulário com os dados que o usuário já digitou
                    return render_template('client_form.html', title="Novo Cliente", client=None)
            # --- FIM DA VALIDAÇÃO ---

            if Client.query.filter_by(name=name).first():
                flash('Já existe um cliente com este nome.', 'warning')
            else:
                client = Client(
                    name=name, address=request.form.get('address'),
                    contact_person=request.form.get('contact_person'),
                    phone=phone # Salva o telefone com a máscara
                )
                db.session.add(client)
                db.session.commit()
                flash('Cliente cadastrado com sucesso!', 'success')
                return redirect(url_for('client_list'))
            
        return render_template('client_form.html', title="Novo Cliente", client=None)



    # Em app.py
    @app.route('/client/edit/<int:client_id>', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def edit_client(client_id):
        client = db.session.get(Client, client_id)
        if not client:
            abort(404)
        if request.method == 'POST':
            phone = request.form.get('phone')

            # --- INÍCIO DA VALIDAÇÃO ---
            if phone: # Apenas valida se um telefone foi digitado
                cleaned_phone = re.sub(r'\D', '', phone)
                if not re.match(r'^\d{10,11}$', cleaned_phone):
                    flash('O número de telefone informado é inválido.', 'danger')
                    return render_template('client_form.html', title="Editar Cliente", client=client)
            # --- FIM DA VALIDAÇÃO ---

            client.name, client.address = request.form.get('name'), request.form.get('address')
            client.contact_person = request.form.get('contact_person')
            client.phone = phone
            db.session.commit()
            msg = f"O cliente '{client.name}' foi atualizado por {current_user.username}."
            admins = User.query.filter_by(role='admin').all()
            for admin in admins:
                if admin.id != current_user.id:
                    notif = Notification(user_id=admin.id, message=msg, url=url_for('client_list'))
                    db.session.add(notif)
            db.session.commit()
            flash('Cliente atualizado com sucesso!', 'success')
            return redirect(url_for('client_list'))

        return render_template('client_form.html', title="Editar Cliente", client=client)
    


    # arquivar cliente

    @app.route('/client/archive/<int:client_id>', methods=['POST'])
    @login_required
    @admin_required
    def toggle_archive_client(client_id):
        client = db.session.get(Client, client_id)
        if client:
            # Inverte o status de arquivamento
            client.is_archived = not client.is_archived
            db.session.commit()
            flash(f'Cliente "{client.name}" {"arquivado" if client.is_archived else "restaurado"} com sucesso.', 'success')
        else:
            flash('Cliente não encontrado.', 'danger')

        # Redireciona de volta para a página de onde o usuário veio
        return redirect(request.referrer or url_for('client_list'))
    

    @app.route('/clients/archived')
    @login_required
    @admin_required
    def archived_clients():
        archived = Client.query.filter_by(is_archived=True).order_by(Client.name).all()
        return render_template('archived_clients.html', clients=archived)
    


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
                admin_msg = f"Tarefa '{task.title}' foi atualizada por {current_user.username}."
                admins = User.query.filter_by(role='admin').all()
                for admin in admins:
                    if admin.id != current_user.id:
                        notif = Notification(user_id=admin.id, message=admin_msg, url=url_for('admin_tasks'))
                        db.session.add(notif)
                for assignment in task.assignments:
                    if assignment.user_id != current_user.id:
                        tech_msg = f"A tarefa '{task.title}' que está atribuída a você foi atualizada."
                        notif_technician = Notification(user_id=assignment.user_id, message=tech_msg, url=url_for('technician_tasks'))
                        db.session.add(notif_technician)
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
            admin_msg = f"A tarefa '{task.title}' foi deletada por {current_user.username}."
            admins = User.query.filter_by(role='admin').all()
            for admin in admins:
                if admin.id != current_user.id:
                    notif = Notification(user_id=admin.id, message=admin_msg, url=url_for('admin_tasks'))
                    db.session.add(notif)
            for assignment in task.assignments:
                if assignment.user_id != current_user.id:
                    tech_msg = f"A tarefa '{task.title}' que estava atribuída a você foi deletada."
                    notif_technician = Notification(user_id=assignment.user_id, message=tech_msg, url=url_for('technician_tasks'))
                    db.session.add(notif_technician)
            db.session.commit()
            flash('Tarefa deletada com sucesso.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao deletar tarefa: {e}', 'danger')
        return redirect(url_for('admin_tasks'))

    # Em app.py

    @app.route('/tasks/update_status/<int:assignment_id>', methods=['POST'])
    @login_required
    def update_task_status(assignment_id):
        assignment = db.session.get(TaskAssignment, assignment_id)
        if not assignment:
            abort(404)
        if assignment.user_id != current_user.id and current_user.role != 'admin':
            abort(403)

        try:
            # Pega os dados do formulário
            new_status = request.form.get('status')
            observation = request.form.get('observation') # <-- Pega a observação

            # Atualiza os dados no banco
            assignment.status = new_status
            assignment.observation = observation # <-- Salva a observação

            db.session.commit()

            # Lógica de notificação (já estava correta, mantida aqui)
            creator_id = assignment.task.creator_id
            if creator_id != current_user.id:
                admin_msg = f"O técnico {current_user.username} atualizou a tarefa '{assignment.task.title}' para '{new_status}'."
                admin_notif = Notification(user_id=creator_id, message=admin_msg, url=url_for('admin_tasks'))
                db.session.add(admin_notif)
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
        # Buscando dados para os filtros
        clients = Client.query.filter_by(is_archived=False).order_by(Client.name).all()
        equipments = Equipment.query.filter_by(is_archived=False).order_by(Equipment.code).all()

        # Pegando os valores dos filtros da URL
        client_id = request.args.get('client_id', type=int)
        equipment_id = request.args.get('equipment_id', type=int) # <-- NOVO
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        # Construindo a query base
        query = db.session.query(MaintenanceHistory).join(Equipment)

        # Aplicando os filtros
        if client_id:
            query = query.filter(Equipment.client_id == client_id)
        if equipment_id: # <-- NOVO
            query = query.filter(MaintenanceHistory.equipment_id == equipment_id)
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
                               equipments=equipments, # <-- NOVO
                               records=records,
                               total_cost=total_cost,
                               filters=request.args)
    



    # ####Notificações

    @app.route('/notifications/read/<int:notification_id>')
    @login_required
    def read_notification(notification_id):
        notification = db.session.get(Notification, notification_id)
        if notification and notification.user_id == current_user.id:
            notification.is_read = True
            db.session.commit()

        # Se a notificação tiver uma URL, redireciona para ela. Senão, para o dashboard.
        return redirect(notification.url or url_for('dashboard'))



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
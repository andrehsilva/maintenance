# app.py
import os
from datetime import datetime, date, timedelta
from functools import wraps
import pandas as pd
import click
import openpyxl

import io
import re
import qrcode
import uuid
from werkzeug.utils import secure_filename
from flask import send_file
from flask import (Flask, abort, flash, redirect, render_template, request, url_for, jsonify)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import desc, func, or_
from sqlalchemy import extract
from sqlalchemy.orm import joinedload, subqueryload
from math import ceil
from urllib.parse import quote
import pytz
from flask_migrate import Migrate

# Importa as extensões e os modelos dos novos arquivos
from extensions import db, login_manager
from models import (Client, Equipment, MaintenanceHistory, Task, TaskAssignment, User, Setting, Notification, MaintenanceImage, Lead, Expense, TimeClock, StockItem, MaintenancePartUsed)

from dotenv import load_dotenv 


# --- Define o fuso horário padrão da aplicação ---
FUSO_HORARIO_SP = pytz.timezone('America/Sao_Paulo')

# --- Carrega as variáveis do arquivo .env para o ambiente ---
load_dotenv()

# --- Configurações de Upload ---
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Função de Criação da Aplicação (App Factory) ---
# app.py

# ... (suas importações: os, Flask, SQLAlchemy, etc.)
# Lembre-se de ter estas duas linhas no topo do seu arquivo, antes de tudo:
# from dotenv import load_dotenv
# load_dotenv()

# Em app.py

def format_datetime_local(utc_datetime, fmt=None):
    """
    Filtro Jinja para converter uma data UTC (ciente ou ingênua) para o fuso de SP.
    """
    if not utc_datetime:
        return ""

    # VERIFICAÇÃO IMPORTANTE: Se o datetime do banco for "ingênuo" (sem fuso),
    # nós o tornamos "ciente" de que ele é UTC.
    if utc_datetime.tzinfo is None:
        utc_datetime = pytz.utc.localize(utc_datetime)

    # Agora que temos certeza que é um datetime "ciente", convertemos para o fuso de SP.
    local_datetime = utc_datetime.astimezone(FUSO_HORARIO_SP)
    
    # Se um formato for especificado (ex: '%H:%M'), usa ele.
    if fmt:
        return local_datetime.strftime(fmt)
    
    # Senão, usa o formato padrão completo.
    return local_datetime.strftime('%d/%m/%Y às %H:%M')

def create_app():
    """
    Cria e configura uma instância da aplicação Flask (Padrão App Factory).
    """
    app = Flask(__name__)

    # --- 1. CONFIGURAÇÃO DE SEGREDOS ---
    # Carrega a chave secreta a partir das variáveis de ambiente.
    # É mais seguro e flexível para produção e desenvolvimento.
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chave-padrao-apenas-para-desenvolvimento')

    # --- 2. CONFIGURAÇÃO DO BANCO DE DADOS ---
    # Prioriza a variável de ambiente DATABASE_URL (usada no Easypanel/produção).
    database_url = os.environ.get('DATABASE_URL')
    
    if database_url:
        # Se a variável existe, usa o banco de produção (PostgreSQL).
        # Corrige o dialeto para compatibilidade com SQLAlchemy.
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url.replace("postgres://", "postgresql://", 1)
    else:
        # Se não, usa um banco de dados SQLite local com um caminho absoluto e seguro.
        # Isso evita erros dependendo de onde o comando 'flask' é executado.
        basedir = os.path.abspath(os.path.dirname(__file__))
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'maintenance.db')

    # Linha de debug: mostra no terminal qual banco de dados está sendo usado.
    print(f"--- INFO: Conectando ao banco de dados em: {app.config['SQLALCHEMY_DATABASE_URI']} ---")
    
    # Otimização recomendada para o SQLAlchemy.
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Configuração da pasta de uploads.
    UPLOAD_FOLDER = 'uploads'
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['UPLOAD_FOLDER'] = os.path.join(basedir, UPLOAD_FOLDER)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Isso "ensina" o Jinja (motor de templates) sobre o nosso novo filtro.
    app.jinja_env.filters['localdatetime'] = format_datetime_local
    # ---------------------------------------------

    # --- 3. INICIALIZAÇÃO DAS EXTENSÕES ---
    # Associa as extensões (db, login_manager) com a instância 'app'.
    db.init_app(app)
    Migrate(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = "Por favor, faça o login para acessar esta página."


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
        return User.query.get(int(user_id))

    # --- 4. REGISTRO DE ROTAS E COMANDOS ---
    # Mantém seu código organizado chamando as funções que registram tudo.
    register_routes(app)
    register_commands(app)
    
    # --- 5. RETORNA A APLICAÇÃO PRONTA ---
    return app



    

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
    MAINTENANCE_CATEGORIES = ['Instalação','Manutenção Preventiva', 'Manutenção Corretiva', 'Manutenção Proativa']

    # Em app.py, adicione esta nova rota

    @app.route('/')
    def index():
        # Se o usuário já estiver logado, redireciona para o painel principal
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        # Se não, exibe a página de vendas
        return render_template('landing_page.html')

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
        users = User.query.order_by(User.name).all() # Ordenar por nome
        return render_template('user_list.html', users=users)

    @app.route('/user/new', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def create_user():
        """Cria um novo usuário (admin ou técnico)."""
        if request.method == 'POST':
            username = request.form.get('username')
            name = request.form.get('name')
            email = request.form.get('email')
            cpf = request.form.get('cpf')
            password = request.form.get('password')
            role = request.form.get('role')

            if not all([username, name, email, cpf, password, role]):
                flash('Todos os campos marcados com * são obrigatórios.', 'danger')
                return render_template('user_form.html', title="Criar Novo Usuário", user=None, form_data=request.form)

            # Verifica se username, email ou cpf já existem
            existing_user = User.query.filter(
                or_(User.username == username, User.email == email, User.cpf == cpf)
            ).first()
            if existing_user:
                if existing_user.username == username:
                    flash('Este nome de usuário já está em uso.', 'warning')
                elif existing_user.email == email:
                    flash('Este e-mail já está cadastrado.', 'warning')
                elif existing_user.cpf == cpf:
                    flash('Este CPF já está cadastrado.', 'warning')
                return render_template('user_form.html', title="Criar Novo Usuário", user=None, form_data=request.form)
            
            # Cria o novo usuário com todos os campos
            new_user = User(
                username=username, 
                name=name, 
                email=email, 
                cpf=cpf, 
                role=role,
                is_active=True # Admin criando usuário já o torna ativo
            )
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash(f'Usuário "{name}" criado com sucesso!', 'success')
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
            name = request.form.get('name')
            email = request.form.get('email')
            cpf = request.form.get('cpf')
            password = request.form.get('password') # Senha é opcional na edição
            role = request.form.get('role')

            # Verifica se os dados únicos já estão em uso por OUTRO usuário
            existing_user = User.query.filter(
                User.id != user_id,
                or_(User.username == username, User.email == email, User.cpf == cpf)
            ).first()
            if existing_user:
                if existing_user.username == username:
                    flash('Este nome de usuário já está em uso por outra conta.', 'warning')
                elif existing_user.email == email:
                    flash('Este e-mail já está em uso por outra conta.', 'warning')
                elif existing_user.cpf == cpf:
                    flash('Este CPF já está em uso por outra conta.', 'warning')
                return render_template('user_form.html', title="Editar Usuário", user=user, form_data=request.form)

            user.username = username
            user.name = name
            user.email = email
            user.cpf = cpf
            user.role = role
            # Só atualiza a senha se uma nova for fornecida
            if password:
                user.set_password(password)
            
            db.session.commit()
            flash(f'Usuário "{name}" atualizado com sucesso!', 'success')
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
    # Em app.py, substitua a rota /settings existente por esta versão corrigida:

    @app.route('/settings', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def manage_settings():
        if request.method == 'POST':
            try:
                # Salva o número de dias para o alerta
                new_days_str = request.form.get('warning_days')
                if new_days_str:
                    new_days_int = int(new_days_str)
                    setting_days = db.session.get(Setting, 'maintenance_warning_days')
                    if setting_days:
                        setting_days.value = str(new_days_int)
                    else:
                        setting_days = Setting(key='maintenance_warning_days', value=str(new_days_int))
                        db.session.add(setting_days)

                # CORREÇÃO: Salva o template da mensagem do WhatsApp
                whatsapp_template_str = request.form.get('whatsapp_template')
                if whatsapp_template_str is not None:  # Permite string vazia
                    setting_template = db.session.get(Setting, 'whatsapp_message_template')
                    if setting_template:
                        setting_template.value = whatsapp_template_str
                    else:
                        setting_template = Setting(key='whatsapp_message_template', value=whatsapp_template_str)
                        db.session.add(setting_template)

                # IMPORTANTE: Commit após todas as alterações
                db.session.commit()
                flash('Configurações salvas com sucesso!', 'success')

            except (ValueError, TypeError) as e:
                db.session.rollback()
                flash(f'Erro nos dados fornecidos: {str(e)}', 'danger')
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao salvar configurações: {str(e)}', 'danger')

            return redirect(url_for('manage_settings'))

        # Para GET, busca os valores atuais para exibir no formulário
        setting_days = db.session.get(Setting, 'maintenance_warning_days')
        current_days = setting_days.value if setting_days else '15'

        setting_template = db.session.get(Setting, 'whatsapp_message_template')
        default_template = (
            "Olá, {client_name}! Somos da SacadaGear e gostaríamos de lembrar sobre a manutenção do seu equipamento "
            "'{equipment_model} ({equipment_code})', agendada para o dia {maintenance_date}. "
            "Podemos confirmar o agendamento?"
        )
        current_template = setting_template.value if setting_template else default_template

        return render_template('settings.html', 
                             warning_days=current_days, 
                             whatsapp_template=current_template)
    


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

    # DENTRO DA FUNÇÃO register_routes(app):
    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            username = request.form.get('username')
            name = request.form.get('name')
            email = request.form.get('email')
            cpf = request.form.get('cpf')
            password = request.form.get('password')

            # Validação de campos
            if not all([username, name, email, cpf, password]):
                 flash('Todos os campos são obrigatórios.', 'danger')
                 return redirect(url_for('register'))

            # Verifica se username, email ou cpf já existem
            existing_user = User.query.filter(
                or_(User.username == username, User.email == email, User.cpf == cpf)
            ).first()
            if existing_user:
                if existing_user.username == username:
                    flash('Este nome de usuário já existe.', 'warning')
                elif existing_user.email == email:
                    flash('Este e-mail já está cadastrado.', 'warning')
                elif existing_user.cpf == cpf:
                    flash('Este CPF já está cadastrado.', 'warning')
                return redirect(url_for('register'))

            # O primeiro usuário é admin E ativo. Os demais começam inativos.
            is_first_user = User.query.count() == 0
            role = 'admin' if is_first_user else 'technician'

            new_user = User(
                username=username,
                name=name,
                email=email,
                cpf=cpf,
                role=role, 
                is_active=is_first_user
            )
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()

            if is_first_user:
                flash('Conta de administrador criada com sucesso! Faça o login.', 'success')
            else:
                # Notifica os admins sobre o novo registro pendente
                msg = f"Novo usuário '{name}' se registrou e aguarda aprovação."
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
    

    
    # --- ROTAS DE HISTÓRICO DE MANUTENÇÃO (ATUALIZADAS) ---
    @app.route('/history/new/<int:equipment_id>', methods=['GET', 'POST'])
    @login_required
    def new_maintenance_history(equipment_id):
        equipment = db.session.get(Equipment, equipment_id)
        if not equipment:
            abort(404)
        if current_user.role != 'admin' and equipment.user_id != current_user.id:
            abort(403)

        # --- Lógica de Envio de Dados (POST) ---
        if request.method == 'POST':
            try:
                # 1. Pega os dados básicos do formulário
                maintenance_date = datetime.strptime(request.form.get('maintenance_date'), '%Y-%m-%d').date()
                cost_str = request.form.get('cost')
                labor_cost = float(cost_str.replace(',', '.')) if cost_str else 0.0

                # Pega as listas de peças e quantidades
                part_ids = request.form.getlist('part_ids')
                part_quantities = request.form.getlist('part_quantities')

                total_parts_cost = 0.0
                parts_to_process = []

                # 2. Loop de VALIDAÇÃO: Verifica o estoque e calcula o custo das peças ANTES de salvar
                for part_id, qty_str in zip(part_ids, part_quantities):
                    if part_id and qty_str:
                        item_id = int(part_id)
                        quantity_used = int(qty_str)

                        item = db.session.get(StockItem, item_id)
                        if not item or item.quantity < quantity_used:
                            error_msg = f'Estoque insuficiente para "{item.name}". Disponível: {item.quantity}, Tentativa de uso: {quantity_used}.'
                            flash(error_msg, 'danger')
                            # Se falhar, precisa recarregar o form com os dados corretos
                            raise ValueError(error_msg)

                        if item.unit_cost:
                            total_parts_cost += float(item.unit_cost) * quantity_used

                        parts_to_process.append({'item': item, 'quantity': quantity_used})

                # 3. Cria o registro de manutenção principal
                history_entry = MaintenanceHistory(
                    maintenance_date=maintenance_date,
                    category=request.form.get('category'),
                    description=request.form.get('description'),
                    equipment_id=equipment_id,
                    technician_id=current_user.id,
                    cost=float(labor_cost) + total_parts_cost # Custo total = Mão de Obra + Peças
                )
                db.session.add(history_entry)
                db.session.flush() # Força o ID para o history_entry

                # 4. Loop de EXECUÇÃO: Dá baixa no estoque e cria os registros de peças usadas
                for part_data in parts_to_process:
                    part_data['item'].quantity -= part_data['quantity']

                    part_used_entry = MaintenancePartUsed(
                        maintenance_history_id=history_entry.id,
                        stock_item_id=part_data['item'].id,
                        quantity_used=part_data['quantity']
                    )
                    db.session.add(part_used_entry)

                # 5. Lógica de Upload de Fotos (mantida a sua)
                photos = request.files.getlist('photos')
                if len(photos) > 3:
                    raise ValueError("Você pode enviar no máximo 3 fotos.")
                for photo in photos:
                    if photo and allowed_file(photo.filename):
                        ext = photo.filename.rsplit('.', 1)[1].lower()
                        filename = secure_filename(f"{uuid.uuid4()}.{ext}")
                        photo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                        new_image = MaintenanceImage(filename=filename, maintenance_history_id=history_entry.id)
                        db.session.add(new_image)

                # 6. Atualiza o equipamento e notifica
                equipment.last_maintenance_date = maintenance_date
                notify_admins(f"Nova manutenção em '{equipment.code}' por {current_user.username}.", url_for('equipment_history', equipment_id=equipment.id), excluded_user_id=current_user.id)

                db.session.commit() # Salva tudo no banco
                flash('Registro de manutenção e baixa de estoque realizados com sucesso!', 'success')
                return redirect(url_for('equipment_history', equipment_id=equipment_id))

            except (ValueError, TypeError) as e:
                db.session.rollback()
                # A flash message já foi definida no loop de validação se o erro foi de estoque
                if 'Estoque insuficiente' not in str(e):
                    flash(f'Erro nos dados: {e}. Verifique os valores.', 'danger')
            except Exception as e:
                db.session.rollback()
                flash(f'Ocorreu um erro inesperado: {e}', 'danger')

        # --- Lógica de Exibição da Página (GET) ou se o POST falhar ---
        stock_items_from_db = StockItem.query.filter(StockItem.quantity > 0).order_by(StockItem.name).all()
        # Converte a lista para o formato JSON que o AlpineJS espera
        stock_items_json = [
            {'id': item.id, 'name': item.name, 'quantity': item.quantity}
            for item in stock_items_from_db
        ]

        return render_template(
            'maintenance_form.html',
            equipment=equipment,
            categories=MAINTENANCE_CATEGORIES,
            stockItems=stock_items_json, # Envia a variável JSON correta
            now=datetime.utcnow()
        )


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
                # --- Devolve as peças antigas para o estoque antes de processar as novas ---
                for part_used in history_record.parts_used:
                    part_used.item.quantity += part_used.quantity_used
                MaintenancePartUsed.query.filter_by(maintenance_history_id=history_id).delete()

                # --- Processa os novos dados do formulário ---
                maintenance_date = datetime.strptime(request.form.get('maintenance_date'), '%Y-%m-%d').date()
                cost_str = request.form.get('cost')
                labor_cost = float(cost_str.replace(',', '.')) if cost_str else 0.0
                
                part_ids = request.form.getlist('part_ids')
                part_quantities = request.form.getlist('part_quantities')

                new_parts_cost = 0.0
                parts_to_process = []

                # Validação de estoque para as novas peças
                for part_id, qty_str in zip(part_ids, part_quantities):
                    if part_id and qty_str:
                        item = db.session.get(StockItem, int(part_id))
                        quantity_used = int(qty_str)
                        if not item or item.quantity < quantity_used:
                            raise ValueError(f'Estoque insuficiente para "{item.name}".')
                        if item.unit_cost:
                            new_parts_cost += float(item.unit_cost) * quantity_used
                        parts_to_process.append({'item': item, 'quantity': quantity_used})

                # Atualiza o registro principal
                history_record.maintenance_date = maintenance_date
                history_record.category = request.form.get('category')
                history_record.description = request.form.get('description')
                history_record.cost = float(labor_cost) + new_parts_cost

                # Dá baixa no estoque e cria os novos registros de peças usadas
                for part_data in parts_to_process:
                    part_data['item'].quantity -= part_data['quantity']
                    new_part_used = MaintenancePartUsed(
                        maintenance_history_id=history_id,
                        stock_item_id=part_data['item'].id,
                        quantity_used=part_data['quantity']
                    )
                    db.session.add(new_part_used)
                
                # Upload de novas fotos
                photos = request.files.getlist('photos')
                if len(photos) + len(history_record.images) > 3:
                    raise ValueError("O total de fotos não pode exceder 3.")
                for photo in photos:
                    if photo and allowed_file(photo.filename):
                        ext = photo.filename.rsplit('.', 1)[1].lower()
                        filename = secure_filename(f"{uuid.uuid4()}.{ext}")
                        photo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                        db.session.add(MaintenanceImage(filename=filename, maintenance_history_id=history_record.id))

                db.session.commit()
                flash('Registro de manutenção atualizado com sucesso!', 'success')
                return redirect(url_for('equipment_history', equipment_id=history_record.equipment_id))

            except (ValueError, TypeError) as e:
                db.session.rollback()
                flash(f'Erro nos dados: {e}.', 'danger')
            except Exception as e:
                db.session.rollback()
                flash(f'Ocorreu um erro inesperado: {e}', 'danger')
        
        # --- Lógica para GET (Exibir o formulário) ---
        stock_items_from_db = StockItem.query.order_by(StockItem.name).all()
        stock_items_json = [{'id': item.id, 'name': item.name, 'quantity': item.quantity} for item in stock_items_from_db]
        
        parts_used_json = [{'stock_item_id': part.stock_item_id, 'quantity_used': part.quantity_used} for part in history_record.parts_used]

        return render_template(
            'maintenance_form.html',
            title="Editar Manutenção",
            equipment=history_record.equipment,
            categories=MAINTENANCE_CATEGORIES,
            history_record=history_record,
            stockItems=stock_items_json,
            parts_used_json=parts_used_json,
            now=datetime.utcnow()
        )

    @app.route('/history/delete_photo/<int:image_id>', methods=['POST'])
    @login_required
    def delete_maintenance_photo(image_id):
        image = db.session.get(MaintenanceImage, image_id)
        if not image:
            abort(404)
        
        history_record = image.maintenance_record
        # Validação de permissão
        if current_user.role != 'admin' and history_record.technician_id != current_user.id:
            abort(403)
            
        try:
            # Deleta o arquivo físico
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], image.filename))
            # Deleta o registro no banco
            db.session.delete(image)
            db.session.commit()
            flash('Foto removida com sucesso.', 'success')
        except OSError:
            flash('Erro ao remover o arquivo da foto, mas o registro foi limpo.', 'warning')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao remover foto: {e}', 'danger')
            
        return redirect(url_for('edit_maintenance', history_id=history_record.id))






    @app.route('/history/delete/<int:history_id>', methods=['POST'])
    @login_required
    def delete_maintenance(history_id):
        history_record = db.session.get(MaintenanceHistory, history_id)
        if not history_record: abort(404)
        if current_user.role != 'admin' and history_record.technician_id != current_user.id: abort(403)
        
        try:
            equipment_id = history_record.equipment_id
            
            # Devolve as peças ao estoque
            for part_used in history_record.parts_used:
                part_used.item.quantity += part_used.quantity_used
            
            # Deleta as imagens
            image_filenames = [image.filename for image in history_record.images]
            for filename in image_filenames:
                try:
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                except OSError:
                    pass
            
            db.session.delete(history_record)
            db.session.commit()
            flash('Registro de manutenção deletado e estoque restaurado.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao deletar registro: {e}', 'danger')
            
        return redirect(url_for('equipment_history', equipment_id=equipment_id))

    
    @app.route('/stock/manual-adjust/<int:item_id>', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def manual_stock_adjust(item_id):
        """Permite ajuste manual de estoque para itens que não requerem tracking."""
        item = db.session.get(StockItem, item_id)
        if not item:
            abort(404)

        if request.method == 'POST':
            try:
                adjustment_type = request.form.get('adjustment_type')
                quantity = int(request.form.get('quantity'))
                reason = request.form.get('reason', '')
                notes = request.form.get('notes', '')

                if adjustment_type == 'add':
                    item.quantity += quantity
                    flash(f'✅ Adicionadas {quantity} unidades ao estoque de "{item.name}".', 'success')
                elif adjustment_type == 'remove':
                    if item.quantity < quantity:
                        flash('❌ Quantidade insuficiente em estoque.', 'danger')
                        return redirect(url_for('manual_stock_adjust', item_id=item_id))
                    item.quantity -= quantity
                    flash(f'✅ Removidas {quantity} unidades do estoque de "{item.name}".', 'success')

                # Aqui você pode registrar o ajuste em uma tabela de log se desejar
                db.session.commit()
                return redirect(url_for('stock_list'))

            except (ValueError, TypeError):
                flash('❌ Quantidade inválida.', 'danger')
            except Exception as e:
                db.session.rollback()
                flash(f'❌ Erro ao ajustar estoque: {e}', 'danger')

        return render_template('manual_stock_adjust.html', item=item)




    @app.route('/stock/quick-adjust/<int:item_id>', methods=['POST'])
    @login_required
    @admin_required
    def quick_stock_adjust(item_id):
        """Ajuste rápido de estoque diretamente da lista."""
        item = db.session.get(StockItem, item_id)
        if not item:
            flash('Item não encontrado.', 'danger')
            return redirect(url_for('stock_list'))

        if item.requires_tracking:
            flash('Este item requer controle automático. Use o sistema de manutenções.', 'warning')
            return redirect(url_for('stock_list'))

        try:
            adjustment_type = request.form.get('adjustment_type')
            quantity = int(request.form.get('quantity'))

            if adjustment_type == 'add':
                item.quantity += quantity
                flash(f'Adicionadas {quantity} unidades ao estoque de "{item.name}".', 'success')
            elif adjustment_type == 'remove':
                if item.quantity < quantity:
                    flash('Quantidade insuficiente em estoque.', 'danger')
                    return redirect(url_for('stock_list'))
                item.quantity -= quantity
                flash(f'Removidas {quantity} unidades do estoque de "{item.name}".', 'success')

            db.session.commit()

        except (ValueError, TypeError):
            flash('Quantidade inválida.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao ajustar estoque: {e}', 'danger')

        return redirect(url_for('stock_list'))


    @app.route('/reports/stock-movement')
    @login_required
    @admin_required
    def stock_movement_report():
        """Relatório completo de movimentação de estoque."""
        # Filtros
        item_id = request.args.get('item_id', type=int)
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        # Query para itens de estoque
        items = StockItem.query.order_by(StockItem.name).all()
        
        # Query para movimentações de entrada (compras/adicionais)
        # NOTA: Você precisará criar uma tabela para registrar entradas manualmente
        # Por enquanto, vamos focar nas saídas via manutenções
        
        # Query para movimentações de saída (manutenções)
        outgoing_query = db.session.query(
            MaintenancePartUsed.stock_item_id,
            MaintenancePartUsed.quantity_used,
            MaintenanceHistory.maintenance_date,
            Equipment.code.label('equipment_code'),
            Client.name.label('client_name')
        ).join(
            MaintenanceHistory, MaintenancePartUsed.maintenance_history_id == MaintenanceHistory.id
        ).join(
            Equipment, MaintenanceHistory.equipment_id == Equipment.id
        ).join(
            Client, Equipment.client_id == Client.id
        )
        
        # Aplicar filtros
        if item_id:
            outgoing_query = outgoing_query.filter(MaintenancePartUsed.stock_item_id == item_id)
        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            outgoing_query = outgoing_query.filter(MaintenanceHistory.maintenance_date >= start_date)
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            outgoing_query = outgoing_query.filter(MaintenanceHistory.maintenance_date <= end_date)
        
        outgoing_movements = outgoing_query.order_by(desc(MaintenanceHistory.maintenance_date)).all()
        
        # Calcular totais
        total_withdrawals = sum(mov.quantity_used for mov in outgoing_movements)
        
        return render_template('stock_movement_report.html',
                             items=items,
                             outgoing_movements=outgoing_movements,
                             total_withdrawals=total_withdrawals,
                             filters=request.args)
    


    
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
    
    #leads
    @app.route('/quero-uma-demonstracao')
    def lead_form():
        """Exibe a página com o formulário de interesse."""
        return render_template('lead_form.html')

    @app.route('/politica-de-privacidade')
    def privacy_policy():
        """Exibe a página da política de privacidade."""
        return render_template('politica-de-privacidade.html')


    @app.route('/lead/submit', methods=['POST'])
    def submit_lead():
        """Recebe os dados do formulário, salva no banco e retorna um JSON."""
        try:
            nome = request.form.get('nome')
            empresa = request.form.get('empresa')
            whatsapp = request.form.get('whatsapp')
            email = request.form.get('email')

            if not all([nome, empresa, whatsapp, email]):
                return jsonify({'status': 'error', 'message': 'Todos os campos são obrigatórios.'}), 400

            # --- CORREÇÃO FINAL ---
            # Verifica se o e-mail OU o whatsapp já existem no banco de dados
            existing_lead = Lead.query.filter(
                or_(Lead.email == email, Lead.whatsapp == whatsapp)
            ).first()

            if existing_lead:
                # Se o lead já existe, retorna sucesso para não criar dados duplicados.
                return jsonify({'status': 'success', 'message': 'Usuário já cadastrado.'})
            # --- FIM DA CORREÇÃO ---

            # Se não existir, cria um novo lead
            new_lead = Lead(
                nome=nome,
                empresa=empresa,
                whatsapp=whatsapp,
                email=email
            )
            db.session.add(new_lead)

            #msg = f"Novo lead recebido de '{nome}' da empresa '{empresa}'."
            #notify_admins(msg, url_for('list_leads'))

            db.session.commit()

            return jsonify({'status': 'success'})

        except Exception as e:
            db.session.rollback()
            import traceback
            traceback.print_exc()
            return jsonify({'status': 'error', 'message': 'Ocorreu um erro interno.'}), 500

    @app.route('/leads')
    @login_required
    @admin_required
    def list_leads():
        """Exibe a lista de leads capturados para administradores."""
        page = request.args.get('page', 1, type=int)
        per_page = 15 # Ou o número que preferir

        pagination = Lead.query.order_by(desc(Lead.created_at)).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return render_template('leads.html', pagination=pagination)
    
    # --- NOVAS ROTAS PARA GERENCIAMENTO DE DESPESAS ---

    @app.route('/expenses', methods=['GET', 'POST'])
    @login_required
    def manage_expenses():
        selected_date_str = request.args.get('date')
        try:
            selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date() if selected_date_str else date.today()
        except ValueError:
            selected_date = date.today()

        # --- Lógica de Registro (POST) ---
        if request.method == 'POST':
            try:
                expense_date_str = request.form.get('date')
                expense_date = datetime.strptime(expense_date_str, '%Y-%m-%d').date()
                category = request.form.get('category')
                value_str = request.form.get('value')
                description = request.form.get('description')

                if not category or not value_str:
                    flash('Categoria e Valor são campos obrigatórios.', 'danger')
                    return redirect(url_for('manage_expenses', date=expense_date_str))

                value = float(value_str.replace(',', '.'))

                new_expense = Expense(
                    date=expense_date, category=category, value=value,
                    description=description, user_id=current_user.id
                )
                db.session.add(new_expense)
                db.session.commit()
                flash('Despesa registrada com sucesso!', 'success')
                return redirect(url_for('manage_expenses', date=expense_date_str))

            except (ValueError, TypeError):
                flash('O valor informado é inválido. Use um formato como 50.75.', 'danger')
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao registrar despesa: {e}', 'danger')

            return redirect(url_for('manage_expenses', date=selected_date.strftime('%Y-%m-%d')))

        # --- Lógica de Exibição (GET) ---

        # CORREÇÃO: Calcula as datas de navegação aqui
        previous_day = selected_date - timedelta(days=1)
        next_day = selected_date + timedelta(days=1)

        start_of_week = selected_date - timedelta(days=(selected_date.weekday() + 1) % 7)
        end_of_week = start_of_week + timedelta(days=6)

        daily_expenses = Expense.query.filter_by(user_id=current_user.id, date=selected_date).order_by(Expense.id.desc()).all()

        weekly_total_query = db.session.query(func.sum(Expense.value)).filter(
            Expense.user_id == current_user.id,
            Expense.date >= start_of_week,
            Expense.date <= end_of_week
        ).scalar()
        weekly_total = weekly_total_query or 0.0

        expense_categories = ['Alimentação', 'Combustível ', 'Pedágio', 'Lanche', 'Gastos Diversos']

        return render_template('expenses.html', 
                               daily_expenses=daily_expenses, 
                               categories=expense_categories,
                               selected_date=selected_date,
                               weekly_total=weekly_total,
                               start_of_week=start_of_week,
                               end_of_week=end_of_week,
                               previous_day=previous_day, # Passa a data para o template
                               next_day=next_day)         # Passa a data para o template


    @app.route('/expenses/delete/<int:expense_id>', methods=['POST'])
    @login_required
    def delete_expense(expense_id):
        """Permite que um usuário delete sua própria despesa."""
        expense = db.session.get(Expense, expense_id)
        if not expense:
            abort(404)
        
        # Garante que o usuário só pode deletar suas próprias despesas (a menos que seja admin)
        if expense.user_id != current_user.id and current_user.role != 'admin':
            abort(403)
        
        try:
            db.session.delete(expense)
            db.session.commit()
            flash('Despesa removida com sucesso.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao remover despesa: {e}', 'danger')

        # Redireciona de volta para a página de onde veio (seja a do técnico ou a do admin)
        return redirect(request.referrer or url_for('manage_expenses'))


    @app.route('/reports/expenses')
    @login_required
    @admin_required
    def expense_report():
        """Página para o admin visualizar e filtrar todas as despesas."""
        technicians = User.query.filter_by(role='technician').order_by(User.username).all()
        expense_categories = ['Alimentação', 'Gasolina', 'Pedágio', 'Lanche', 'Gastos Diversos']
        
        # Pega os filtros da URL
        tech_id = request.args.get('technician_id', type=int)
        category = request.args.get('category') # NOVO FILTRO
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        # Query base
        query = Expense.query
        
        # Aplica filtros
        if tech_id:
            query = query.filter(Expense.user_id == tech_id)
        if category: # NOVO FILTRO
            query = query.filter(Expense.category == category)
        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            query = query.filter(Expense.date >= start_date)
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            query = query.filter(Expense.date <= end_date)
            
        # Executa a query para obter os registros
        records = query.order_by(desc(Expense.date), Expense.user_id).all()
        
        # Calcula o total
        total_value = sum(record.value for record in records if record.value is not None)

        return render_template('expense_report.html', 
                               technicians=technicians, 
                               records=records,
                               total_value=total_value,
                               categories=expense_categories, # Passa a lista de categorias
                               filters=request.args)

    @app.route('/export/expenses')
    @login_required
    @admin_required
    def export_expenses():
        """Gera um arquivo Excel com o relatório de despesas filtrado."""
        try:
            # Pega os filtros da URL (mesma lógica do relatório visual)
            tech_id = request.args.get('technician_id', type=int)
            category = request.args.get('category')
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')

            # Query base
            query = Expense.query.options(joinedload(Expense.technician))
            
            # Aplica filtros
            if tech_id:
                query = query.filter(Expense.user_id == tech_id)
            if category:
                query = query.filter(Expense.category == category)
            if start_date_str:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                query = query.filter(Expense.date >= start_date)
            if end_date_str:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                query = query.filter(Expense.date <= end_date)
            
            records = query.order_by(desc(Expense.date), Expense.user_id).all()

            # Prepara os dados para o DataFrame
            data_for_df = [{
                'Data': record.date.strftime('%d/%m/%Y'),
                'Técnico': record.technician.username,
                'Categoria': record.category,
                'Descrição': record.description,
                'Valor (R$)': float(record.value)
            } for record in records]

            # Cria o DataFrame com pandas
            df = pd.DataFrame(data_for_df)

            # Cria o arquivo Excel em memória
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Despesas')
            output.seek(0)
            
            timestamp = datetime.now(FUSO_HORARIO_SP).strftime("%Y-%m-%d")
            return send_file(
                output,
                as_attachment=True,
                download_name=f'relatorio_despesas_{timestamp}.xlsx',
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
        except Exception as e:
            flash(f"Erro ao gerar o relatório Excel: {e}", "danger")
            return redirect(url_for('expense_report'))


    @app.route('/export/maintenance')
    @login_required
    @admin_required
    def export_maintenance():
        """Gera um arquivo Excel com o relatório completo de histórico de manutenções."""
        try:
            # CORREÇÃO: Esta abordagem é compatível com a configuração do seu banco de dados.
            # 1. Busca os equipamentos com seus clientes.
            equipments = Equipment.query.options(
                joinedload(Equipment.client)
            ).order_by(Equipment.code).all()

            data_for_df = []
            # 2. Itera sobre cada equipamento e carrega seu histórico com o técnico de forma otimizada.
            for eq in equipments:
                # A ordenação já vem da definição do modelo (order_by)
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

            timestamp = datetime.now().strftime("%Y-%m-%d")
            return send_file(
                output,
                as_attachment=True,
                download_name=f'relatorio_manutencoes_{timestamp}.xlsx',
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
        except Exception as e:
            flash(f"Erro ao gerar o relatório Excel: {e}", "danger")
            return redirect(url_for('full_history'))

    @app.route('/time-clock', methods=['GET'])
    @login_required
    def time_clock_page():
        """Página para o técnico registrar seu ponto."""
        today = date.today()
        # Busca o registro de hoje para o usuário logado
        todays_record = TimeClock.query.filter_by(user_id=current_user.id, date=today).first()
        return render_template('time_clock.html', record=todays_record, today=today)




    @app.route('/time-clock/register', methods=['POST'])
    @login_required
    def register_time_clock():
        """Registra uma entrada ou saída no ponto."""
        action = request.form.get('action')
        today = date.today()
        
        # Encontra ou cria o registro do dia
        record = TimeClock.query.filter_by(user_id=current_user.id, date=today).first()
        if not record:
            record = TimeClock(user_id=current_user.id, date=today)
            db.session.add(record)

        now = datetime.now(FUSO_HORARIO_SP)
        message = "Ação inválida."

        # Atualiza o campo correspondente à ação
        if action == 'morning_in' and not record.morning_check_in:
            record.morning_check_in = now
            message = f"Entrada da manhã registrada às {now.strftime('%H:%M')}."
        elif action == 'morning_out' and record.morning_check_in and not record.morning_check_out:
            record.morning_check_out = now
            message = f"Saída da manhã registrada às {now.strftime('%H:%M')}."
        elif action == 'afternoon_in' and record.morning_check_out and not record.afternoon_check_in:
            record.afternoon_check_in = now
            message = f"Entrada da tarde registrada às {now.strftime('%H:%M')}."
        elif action == 'afternoon_out' and record.afternoon_check_in and not record.afternoon_check_out:
            record.afternoon_check_out = now
            message = f"Saída da tarde registrada às {now.strftime('%H:%M')}."
        
        try:
            db.session.commit()
            flash(message, 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao registrar ponto: {e}", 'danger')

        return redirect(url_for('time_clock_page'))


    @app.route('/reports/time-clock')
    @login_required
    @admin_required
    def time_clock_report():
        """Exibe o relatório de ponto para o admin."""
        technicians = User.query.filter(User.role != 'admin').order_by(User.username).all()


        # Filtros
        tech_id = request.args.get('technician_id', type=int)
        month_str = request.args.get('month', datetime.now().strftime('%Y-%m'))


        try:
            year, month = map(int, month_str.split('-'))
        except ValueError:
            year, month = datetime.now().year, datetime.now().month
            month_str = f"{year}-{month:02d}"


    # Query base
        query = TimeClock.query


    # Aplica filtro por técnico
        if tech_id:
            query = query.filter(TimeClock.user_id == tech_id)


        # Aplica filtro por ano e mês (compatível com SQLite e Postgres)
        query = query.filter(
            extract('year', TimeClock.date) == year,
            extract('month', TimeClock.date) == month
            )


        records = query.order_by(desc(TimeClock.date), TimeClock.user_id).all()


        # Calcula o total de horas do período filtrado
        total_seconds = 0
        for record in records:
            if record.morning_check_in and record.morning_check_out:
                total_seconds += (record.morning_check_out - record.morning_check_in).total_seconds()
            if record.afternoon_check_in and record.afternoon_check_out:
                total_seconds += (record.afternoon_check_out - record.afternoon_check_in).total_seconds()


        total_hours = f"{(total_seconds / 3600):.2f}".replace('.', ',')


        return render_template(
            'time_clock_report.html',
            technicians=technicians,
            records=records,
            total_hours=total_hours,
            filters=request.args,
            month_filter=month_str
        )



    # --- ROTA PARA PAINEL DE NOTIFICAÇÕES WHATSAPP ---
    @app.route('/notifications/whatsapp')
    @login_required
    @admin_required
    def whatsapp_notifications():
        try:
            # Busca o template da mensagem no banco de dados
            template_setting = db.session.get(Setting, 'whatsapp_message_template')
            default_template = (
                "Olá, {client_name}! Gostaríamos de lembrar sobre a manutenção do seu equipamento "
                "'{equipment_model} ({equipment_code})', agendada para o dia {maintenance_date}."
            )
            message_template = template_setting.value if template_setting else default_template
            
            all_active_equipments = Equipment.query.filter_by(is_archived=False).all()
            due_equipments = [eq for eq in all_active_equipments if eq.status == 'Próximo do vencimento']
            notifications_list = []

            for equipment in due_equipments:
                if not equipment.client or not equipment.client.phone:
                    continue

                cleaned_phone = re.sub(r'\D', '', equipment.client.phone)
                
                # Monta a mensagem usando o template do banco de dados
                message = message_template.format(
                    client_name=(equipment.client.contact_person or equipment.client.name),
                    equipment_model=equipment.model,
                    equipment_code=equipment.code,
                    maintenance_date=equipment.next_maintenance_date.strftime('%d/%m/%Y')
                )
                
                notifications_list.append({
                    'equipment': equipment,
                    'whatsapp_link': f"https://wa.me/55{cleaned_phone}?text={quote(message)}" # Usa a mensagem formatada e codificada
                })

            return render_template('whatsapp_notifications.html', notifications_list=notifications_list)
        except Exception as e:
            flash(f"Erro ao carregar o painel de notificações: {e}", "danger")
            return redirect(url_for('dashboard'))
        


    # --- ROTAS DE GERENCIAMENTO DE ESTOQUE (ADMIN) ---
    @app.route('/stock')
    @login_required
    @admin_required
    def stock_list():
        """Exibe a lista de itens em estoque."""
        items = StockItem.query.order_by(StockItem.name).all()
        return render_template('stock_list.html', items=items)

    # No método add_stock_item
    @app.route('/stock/item/new', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def add_stock_item():
        """Adiciona um novo item ao estoque."""
        if request.method == 'POST':
            try:
                name = request.form.get('name')
                if not name:
                    flash('O nome do item é obrigatório.', 'danger')
                    return render_template('stock_form.html', title="Novo Item de Estoque", item=None, form_data=request.form)
                if StockItem.query.filter_by(name=name).first():
                    flash('Já existe um item com este nome.', 'warning')
                    return render_template('stock_form.html', title="Novo Item de Estoque", item=None, form_data=request.form)
                
                # CORREÇÃO: Converter string para booleano
                requires_tracking_str = request.form.get('requires_tracking')
                requires_tracking = requires_tracking_str.lower() == 'true' if requires_tracking_str else True
                
                new_item = StockItem(
                    name=name,
                    sku=request.form.get('sku'),
                    description=request.form.get('description'),
                    quantity=int(request.form.get('quantity', 0)),
                    low_stock_threshold=int(request.form.get('low_stock_threshold', 5)),
                    unit_cost=float(request.form.get('unit_cost').replace(',', '.')) if request.form.get('unit_cost') else None,
                    requires_tracking=requires_tracking  # CORREÇÃO
                )
                db.session.add(new_item)
                db.session.commit()
                flash(f'Item "{name}" adicionado ao estoque com sucesso!', 'success')
                return redirect(url_for('stock_list'))
            except (ValueError, TypeError):
                flash('Valores numéricos inválidos. Verifique Quantidade, Nível de Alerta e Custo.', 'danger')
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao adicionar item: {e}', 'danger')
        return render_template('stock_form.html', title="Novo Item de Estoque", item=None, form_data={})

    # No método edit_stock_item
    @app.route('/stock/item/edit/<int:item_id>', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def edit_stock_item(item_id):
        """Edita um item existente no estoque."""
        item = db.session.get(StockItem, item_id)
        if not item: abort(404)
        if request.method == 'POST':
            try:
                name = request.form.get('name')
                if not name:
                    flash('O nome do item é obrigatório.', 'danger')
                    return render_template('stock_form.html', title="Editar Item", item=item, form_data=request.form)
                existing_item = StockItem.query.filter(StockItem.name == name, StockItem.id != item_id).first()
                if existing_item:
                    flash('Já existe outro item com este nome.', 'warning')
                    return render_template('stock_form.html', title="Editar Item", item=item, form_data=request.form)

                # CORREÇÃO: Converter string para booleano
                requires_tracking_str = request.form.get('requires_tracking')
                requires_tracking = requires_tracking_str.lower() == 'true' if requires_tracking_str else True

                item.name, item.sku, item.description = name, request.form.get('sku'), request.form.get('description')
                item.quantity = int(request.form.get('quantity', 0))
                item.low_stock_threshold = int(request.form.get('low_stock_threshold', 5))
                item.unit_cost = float(request.form.get('unit_cost').replace(',', '.')) if request.form.get('unit_cost') else None
                item.requires_tracking = requires_tracking  # CORREÇÃO

                db.session.commit()
                flash(f'Item "{name}" atualizado com sucesso!', 'success')
                return redirect(url_for('stock_list'))
            except (ValueError, TypeError):
                flash('Valores numéricos inválidos.', 'danger')
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao atualizar item: {e}', 'danger')
        return render_template('stock_form.html', title="Editar Item", item=item, form_data=item.__dict__)



    @app.route('/stock/item/delete/<int:item_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_stock_item(item_id):
        """Deleta um item do estoque."""
        item = db.session.get(StockItem, item_id)
        if not item:
            flash('Item não encontrado.', 'danger')
            return redirect(url_for('stock_list'))
        if MaintenancePartUsed.query.filter_by(stock_item_id=item_id).first():
            flash(f'Não é possível excluir o item "{item.name}", pois ele já foi utilizado em registros de manutenção.', 'danger')
            return redirect(url_for('stock_list'))
        try:
            db.session.delete(item)
            db.session.commit()
            flash(f'Item "{item.name}" excluído com sucesso.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao excluir item: {e}', 'danger')
        return redirect(url_for('stock_list'))
    


     ### NOVAS ROTAS DE EXPORTAÇÃO ADICIONADAS AQUI ###

    @app.route('/export/financial')
    @login_required
    @admin_required
    def export_financial():
        """Gera um arquivo Excel com o relatório financeiro filtrado."""
        try:
            client_id = request.args.get('client_id', type=int)
            equipment_id = request.args.get('equipment_id', type=int)
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')

            query = db.session.query(MaintenanceHistory).join(Equipment).options(
                joinedload(MaintenanceHistory.equipment).joinedload(Equipment.client)
            )

            if client_id:
                query = query.filter(Equipment.client_id == client_id)
            if equipment_id:
                query = query.filter(MaintenanceHistory.equipment_id == equipment_id)
            if start_date_str:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                query = query.filter(MaintenanceHistory.maintenance_date >= start_date)
            if end_date_str:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                query = query.filter(MaintenanceHistory.maintenance_date <= end_date)

            records = query.order_by(desc(MaintenanceHistory.maintenance_date)).all()

            data_for_df = [{
                'Data': record.maintenance_date.strftime('%d/%m/%Y'),
                'Equipamento (Código)': record.equipment.code,
                'Equipamento (Modelo)': record.equipment.model,
                'Cliente': record.equipment.client.name,
                'Custo (R$)': float(record.cost) if record.cost else 0.0
            } for record in records]

            df = pd.DataFrame(data_for_df)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Financeiro')
            output.seek(0)
            
            timestamp = datetime.now(FUSO_HORARIO_SP).strftime("%Y-%m-%d")
            return send_file(
                output, as_attachment=True,
                download_name=f'relatorio_financeiro_{timestamp}.xlsx',
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
        except Exception as e:
            flash(f"Erro ao gerar o relatório Excel: {e}", "danger")
            return redirect(url_for('financial_report'))

    @app.route('/export/time-clock')
    @login_required
    @admin_required
    def export_time_clock():
        """Gera um arquivo Excel com o relatório de ponto filtrado."""
        try:
            tech_id = request.args.get('technician_id', type=int)
            month_str = request.args.get('month', datetime.now().strftime('%Y-%m'))
            year, month = map(int, month_str.split('-'))

            query = TimeClock.query.options(joinedload(TimeClock.technician))
            if tech_id:
                query = query.filter(TimeClock.user_id == tech_id)
            query = query.filter(
                extract('year', TimeClock.date) == year,
                extract('month', TimeClock.date) == month
            )
            records = query.order_by(desc(TimeClock.date), TimeClock.user_id).all()

            data_for_df = [{
                'Data': record.date.strftime('%d/%m/%Y'),
                'Técnico': record.technician.username,
                'Entrada Manhã': format_datetime_local(record.morning_check_in, '%H:%M') if record.morning_check_in else '-',
                'Saída Manhã': format_datetime_local(record.morning_check_out, '%H:%M') if record.morning_check_out else '-',
                'Entrada Tarde': format_datetime_local(record.afternoon_check_in, '%H:%M') if record.afternoon_check_in else '-',
                'Saída Tarde': format_datetime_local(record.afternoon_check_out, '%H:%M') if record.afternoon_check_out else '-',
                'Total Horas': record.total_hours
            } for record in records]

            df = pd.DataFrame(data_for_df)
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name=f'Ponto_{month_str}')
            output.seek(0)
            
            timestamp = datetime.now(FUSO_HORARIO_SP).strftime("%Y-%m-%d")
            return send_file(
                output, as_attachment=True,
                download_name=f'relatorio_ponto_{month_str}_{timestamp}.xlsx',
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
        except Exception as e:
            flash(f"Erro ao gerar o relatório Excel: {e}", "danger")
            return redirect(url_for('time_clock_report'))

    # ... (resto do seu código app.py) ...

    @app.route('/export/stock-movement')
    @login_required
    @admin_required
    def export_stock_movement():
        """
        Gera um arquivo Excel com a movimentação de estoque (filtrada) 
        e a situação atual do estoque (completa).
        """
        try:
            # --- 1. LÓGICA PARA A ABA DE MOVIMENTAÇÕES (CÓDIGO EXISTENTE) ---
            item_id = request.args.get('item_id', type=int)
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            
            items_dict = {item.id: item.name for item in StockItem.query.all()}
            
            outgoing_query = db.session.query(
                MaintenancePartUsed, MaintenanceHistory, Equipment, Client
            ).select_from(MaintenancePartUsed).join(
                MaintenanceHistory, MaintenancePartUsed.maintenance_history_id == MaintenanceHistory.id
            ).join(
                Equipment, MaintenanceHistory.equipment_id == Equipment.id
            ).join(
                Client, Equipment.client_id == Client.id
            )
            
            if item_id:
                outgoing_query = outgoing_query.filter(MaintenancePartUsed.stock_item_id == item_id)
            if start_date_str:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                outgoing_query = outgoing_query.filter(MaintenanceHistory.maintenance_date >= start_date)
            if end_date_str:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                outgoing_query = outgoing_query.filter(MaintenanceHistory.maintenance_date <= end_date)
            
            movements = outgoing_query.order_by(desc(MaintenanceHistory.maintenance_date)).all()
    
            movements_data = [{
                'Data': mov.MaintenanceHistory.maintenance_date.strftime('%d/%m/%Y'),
                'Item': items_dict.get(mov.MaintenancePartUsed.stock_item_id, 'Desconhecido'),
                'Quantidade Retirada': mov.MaintenancePartUsed.quantity_used,
                'Equipamento': mov.Equipment.code,
                'Cliente': mov.Client.name
            } for mov in movements]
            df_movements = pd.DataFrame(movements_data)
    
            # --- 2. NOVA LÓGICA PARA A ABA DE ESTOQUE ATUAL ---
            all_items = StockItem.query.order_by(StockItem.name).all()
            stock_status_data = []
            for item in all_items:
                # Lógica para definir o status do item
                if item.quantity <= item.low_stock_threshold:
                    status = 'Crítico'
                elif item.quantity <= item.low_stock_threshold * 2:
                    status = 'Atenção'
                else:
                    status = 'Normal'
                
                stock_status_data.append({
                    'Item': item.name,
                    'SKU': item.sku,
                    'Estoque Atual': item.quantity,
                    'Nível de Alerta': item.low_stock_threshold,
                    'Custo Unitário (R$)': float(item.unit_cost) if item.unit_cost else 0.0,
                    'Status': status
                })
            df_stock_status = pd.DataFrame(stock_status_data)
    
            # --- 3. GERAR O ARQUIVO EXCEL COM AS DUAS ABAS ---
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_stock_status.to_excel(writer, index=False, sheet_name='Estoque Atual')
                df_movements.to_excel(writer, index=False, sheet_name='Movimentações')
            output.seek(0)
    
            timestamp = datetime.now(FUSO_HORARIO_SP).strftime("%Y-%m-%d")
            return send_file(
                output, as_attachment=True,
                download_name=f'relatorio_estoque_{timestamp}.xlsx',
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
        except Exception as e:
            flash(f"Erro ao gerar o relatório Excel: {e}", "danger")
            return redirect(url_for('stock_movement_report'))
    


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
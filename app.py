"""
app.py

Arquivo principal da aplicação (Padrão App Factory).
Responsável por criar, configurar e montar a aplicação Flask,
registrando todas as extensões e blueprints (rotas).
"""
import os
import pytz
from flask import Flask
from flask_migrate import Migrate
from flask_login import current_user
from sqlalchemy import desc
from dotenv import load_dotenv


# Importa as extensões e os modelos
from extensions import db, login_manager
from models import User, Notification

# --- Configurações Iniciais ---
FUSO_HORARIO_SP = pytz.timezone('America/Sao_Paulo')
load_dotenv()


# --- Filtros e Funções Auxiliares da Aplicação ---

def format_datetime_local(utc_datetime, fmt=None):
    """
    Filtro Jinja para converter uma data UTC para o fuso horário de São Paulo.
    """
    if not utc_datetime:
        return ""
    if utc_datetime.tzinfo is None:
        utc_datetime = pytz.utc.localize(utc_datetime)
    local_datetime = utc_datetime.astimezone(FUSO_HORARIO_SP)
    if fmt:
        return local_datetime.strftime(fmt)
    return local_datetime.strftime('%d/%m/%Y às %H:%M')


# Em app.py

def register_blueprints(app):
    """Importa e registra todos os blueprints da aplicação."""
    # Módulos Principais (sempre ativos)
    from routes.core import core_bp
    from routes.auth import auth_bp
    from routes.users import users_bp
    from routes.clients import clients_bp
    from routes.equipment import equipment_bp
    from routes.stock import stock_bp
    from routes.notifications import notifications_bp
    from routes.qrcode import qrcode_bp
    from routes.schedule import schedule_bp 
    
    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(equipment_bp)
    app.register_blueprint(stock_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(qrcode_bp)
    

    # --- Módulos Opcionais ---
    if app.config.get('FEATURE_TASKS_ENABLED'):
        from routes.tasks import tasks_bp
        app.register_blueprint(tasks_bp)

    if app.config.get('FEATURE_EXPENSES_ENABLED'):
        from routes.expenses import expenses_bp
        app.register_blueprint(expenses_bp)

    if app.config.get('FEATURE_TIME_CLOCK_ENABLED'):
        from routes.time_clock import time_clock_bp
        app.register_blueprint(time_clock_bp)

    if app.config.get('FEATURE_REPORTS_ENABLED'):
        from routes.reports import reports_bp
        app.register_blueprint(reports_bp)
        
    if app.config.get('FEATURE_LEADS_ENABLED'):
        from routes.leads import leads_bp
        app.register_blueprint(leads_bp)

    if app.config.get('FEATURE_SCHEDULE_ENABLED'):
        from routes.schedule import schedule_bp
        app.register_blueprint(schedule_bp)


def register_commands(app):
    """Registra comandos CLI para a aplicação."""
    import click

    @app.cli.command("init-db")
    def init_db_command():
        """Limpa os dados existentes e cria novas tabelas."""
        with app.app_context():
            db.drop_all()
            db.create_all()
            click.echo("Banco de dados inicializado com sucesso.")


# --- Função de Criação da Aplicação (App Factory) ---

def create_app():
    """
    Cria e configura a instância principal da aplicação Flask.
    """
    app = Flask(__name__)

    # --- 1. CONFIGURAÇÕES ---
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'uma-chave-secreta-de-desenvolvimento')

    app.config['FEATURE_TASKS_ENABLED'] = os.environ.get('FEATURE_TASKS_ENABLED') == 'True'
    app.config['FEATURE_EXPENSES_ENABLED'] = os.environ.get('FEATURE_EXPENSES_ENABLED') == 'True'
    app.config['FEATURE_TIME_CLOCK_ENABLED'] = os.environ.get('FEATURE_TIME_CLOCK_ENABLED') == 'True'
    app.config['FEATURE_REPORTS_ENABLED'] = os.environ.get('FEATURE_REPORTS_ENABLED') == 'True'
    app.config['FEATURE_LEADS_ENABLED'] = os.environ.get('FEATURE_LEADS_ENABLED') == 'True'
    app.config['FEATURE_SCHEDULE_ENABLED'] = os.environ.get('FEATURE_SCHEDULE_ENABLED') == 'True'

    
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url.replace("postgres://", "postgresql://", 1)
    else:
        basedir = os.path.abspath(os.path.dirname(__file__))
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'maintenance.db')
        
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    app.jinja_env.filters['localdatetime'] = format_datetime_local

    # --- 2. INICIALIZAÇÃO DAS EXTENSÕES ---
    db.init_app(app)
    Migrate(app, db)
  
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'  # Aponta para a rota de login no blueprint 'auth'
    login_manager.login_message = "Por favor, faça o login para acessar esta página."
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # --- 3. PROCESSADORES DE CONTEXTO ---
    @app.context_processor
    def inject_notifications():
        if current_user.is_authenticated:
            unread_count = current_user.notifications.filter_by(is_read=False).count()
            recent_notifs = current_user.notifications.order_by(desc(Notification.timestamp)).limit(5).all()
            return dict(
                unread_notifications_count=unread_count,
                recent_notifications=recent_notifs
            )
        return dict(unread_notifications_count=0, recent_notifications=[])

    # --- 4. REGISTRO DE BLUEPRINTS E COMANDOS ---
    with app.app_context():
        register_blueprints(app)
        register_commands(app)

    # --- 5. RETORNA A APLICAÇÃO PRONTA ---
    return app


# --- Instância da Aplicação para Execução ---
app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
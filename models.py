# models.py
from flask import g
from datetime import datetime, timedelta
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import desc

# Importa a instância 'db' do arquivo de extensões
from extensions import db

class Setting(db.Model):
    """Modelo para armazenar configurações gerais da aplicação."""
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f'<Setting {self.key}>'

class User(UserMixin, db.Model):
    """Modelo para os usuários (operadores)."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='technician')

    equipments = db.relationship('Equipment', backref='operator', lazy=True)
    maintenance_records = db.relationship('MaintenanceHistory', backref='technician', lazy=True)
    created_tasks = db.relationship('Task', back_populates='creator', foreign_keys='Task.creator_id')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Client(db.Model):
    """Modelo para os clientes."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, unique=True)
    address = db.Column(db.String(250), nullable=True)
    contact_person = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    equipments = db.relationship('Equipment', backref='client', lazy=True)

    def __repr__(self):
        return f'<Client {self.name}>'

class Equipment(db.Model):
    """Modelo para os equipamentos."""
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), nullable=False, unique=True)
    model = db.Column(db.String(150), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    install_date = db.Column(db.Date, nullable=True)
    last_maintenance_date = db.Column(db.Date, nullable=True)
    next_maintenance_date = db.Column(db.Date, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    
    maintenance_history = db.relationship('MaintenanceHistory', backref='equipment', lazy='dynamic', cascade="all, delete-orphan")

    @property
    def status(self):
        # Verifica se já buscamos o valor nesta requisição
        if 'warning_days' not in g:
            # Se não, busca no DB e armazena em 'g' (cache da requisição)
            setting = db.session.get(Setting, 'maintenance_warning_days')
            g.warning_days = int(setting.value) if setting else 15
        
        today = datetime.now().date()
        
        if self.next_maintenance_date < today:
            return "Vencido"
        # Usa o valor que buscamos do banco de dados (ou o padrão)
        elif self.next_maintenance_date <= today + timedelta(days=g.warning_days):
            return "Próximo do vencimento"
        else:
            return "Em dia"

    @property
    def last_maintenance_record(self):
        """Retorna o último registro de histórico para este equipamento."""
        return self.maintenance_history.order_by(desc(MaintenanceHistory.maintenance_date)).first()

    def __repr__(self):
        return f'<Equipment {self.code}>'

class MaintenanceHistory(db.Model):
    """Modelo para o histórico de manutenções."""
    id = db.Column(db.Integer, primary_key=True)
    maintenance_date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=False)
    technician_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # CORREÇÃO: Adicionado o campo de custo
    cost = db.Column(db.Numeric(10, 2), nullable=True)

    def __repr__(self):
        return f'<MaintenanceHistory {self.id} for Equipment {self.equipment_id}>'

class Task(db.Model):
    """Modelo para a tarefa criada pelo admin."""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_date = db.Column(db.DateTime, default=datetime.utcnow)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    creator = db.relationship('User', back_populates='created_tasks', foreign_keys=[creator_id])
    assignments = db.relationship('TaskAssignment', backref='task', cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Task {self.title}>'

class TaskAssignment(db.Model):
    """Modelo que liga uma Tarefa a um Técnico e controla o status."""
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(50), default='Não iniciado', nullable=False)
    technician = db.relationship('User')

    def __repr__(self):
        return f'<TaskAssignment for Task {self.task_id} to User {self.user_id}>'
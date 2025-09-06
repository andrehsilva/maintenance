# models.py
from flask import g
from datetime import datetime, timedelta, date # CORREÇÃO: 'date' foi adicionado aqui
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import desc
from flask import url_for
# Importa a instância 'db' do arquivo de extensões
from extensions import db



class Setting(db.Model):
    """Modelo para armazenar configurações gerais da aplicação."""
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(250), nullable=False)

    def __repr__(self):
        return f'<Setting {self.key}>'

class User(UserMixin, db.Model):
    """Modelo para os usuários (operadores)."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)# --- CAMPOS ADICIONADOS ---
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    cpf = db.Column(db.String(14), unique=True, nullable=False) # Armazenado como string para manter a formatação
    role = db.Column(db.String(20), nullable=False, default='technician')
    is_active = db.Column(db.Boolean, default=False, nullable=False)
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
    
    # ADICIONE ESTA LINHA
    is_archived = db.Column(db.Boolean, default=False, nullable=False)

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
    cost = db.Column(db.Float, nullable=True)
    parts_used = db.relationship('MaintenancePartUsed', backref='maintenance_record', lazy='dynamic', cascade="all, delete-orphan")

    images = db.relationship('MaintenanceImage', backref='maintenance_record', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<MaintenanceHistory {self.id} for Equipment {self.equipment_id}>'

class MaintenanceImage(db.Model):
    """Modelo para armazenar as imagens de uma manutenção."""
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(100), nullable=False)
    maintenance_history_id = db.Column(db.Integer, db.ForeignKey('maintenance_history.id'), nullable=False)

    def __repr__(self):
        return f'<MaintenanceImage {self.filename}>'
    

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
    observation = db.Column(db.Text, nullable=True) # Campo para as anotações do técnico
    technician = db.relationship('User')

    def __repr__(self):
        return f'<TaskAssignment for Task {self.task_id} to User {self.user_id}>'
    


class Notification(db.Model):
    """Modelo para as notificações no sistema."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    url = db.Column(db.String(255), nullable=True) # Link para onde a notificação leva
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('notifications', lazy='dynamic'))

    def __repr__(self):
        return f'<Notification {self.id} for User {self.user_id}>'
    
    
    
# Em models.py, adicione esta classe no final do arquivo

class Lead(db.Model):
    __tablename__ = 'leads'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    empresa = db.Column(db.String(150), nullable=False)
    whatsapp = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    
    # GARANTA QUE ESTA LINHA EXISTA E ESTEJA CORRETA
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Lead {self.nome} - {self.empresa}>'
    


class Expense(db.Model):
    """Modelo para armazenar as despesas diárias dos técnicos."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    category = db.Column(db.String(50), nullable=False)
    value = db.Column(db.Numeric(10, 2), nullable=False)
    description = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Relacionamento para acessar o usuário (técnico) facilmente
    technician = db.relationship('User', backref=db.backref('expenses', lazy=True))

    def __repr__(self):
        return f'<Expense {self.id} by User {self.user_id}>'
    
class TimeClock(db.Model):
    """Modelo para armazenar os registros de ponto dos técnicos."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date.today)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    morning_check_in = db.Column(db.DateTime, nullable=True)
    morning_check_out = db.Column(db.DateTime, nullable=True)
    afternoon_check_in = db.Column(db.DateTime, nullable=True)
    afternoon_check_out = db.Column(db.DateTime, nullable=True)

    technician = db.relationship('User', backref=db.backref('time_clocks', lazy=True))

    @property
    def total_hours(self):
        """Calcula o total de horas trabalhadas no dia."""
        total_seconds = 0
        if self.morning_check_in and self.morning_check_out:
            total_seconds += (self.morning_check_out - self.morning_check_in).total_seconds()
        if self.afternoon_check_in and self.afternoon_check_out:
            total_seconds += (self.afternoon_check_out - self.afternoon_check_in).total_seconds()
        
        hours = total_seconds / 3600
        return f"{hours:.2f}".replace('.', ',') if hours > 0 else "0,00"

    def __repr__(self):
        return f'<TimeClock {self.id} for User {self.user_id} on {self.date}>'
    


# --- NOVOS MODELOS PARA CONTROLE DE ESTOQUE ---

class StockItem(db.Model):
    """Modelo para os itens do inventário (peças, insumos)."""
    __tablename__ = 'stock_item'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, unique=True)
    category = db.Column(db.String(100), nullable=False)
    sku = db.Column(db.String(50), nullable=True, unique=True) # Código do item
    description = db.Column(db.Text, nullable=True)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    low_stock_threshold = db.Column(db.Integer, nullable=False, default=5) # Nível para alerta
    unit_cost = db.Column(db.Numeric(10, 2), nullable=True)
    requires_tracking = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f'<StockItem {self.name}>'

class MaintenancePartUsed(db.Model):
    """Tabela que registra quais peças e em que quantidade foram usadas em uma manutenção."""
    __tablename__ = 'maintenance_part_used'
    id = db.Column(db.Integer, primary_key=True)
    maintenance_history_id = db.Column(db.Integer, db.ForeignKey('maintenance_history.id'), nullable=False)
    stock_item_id = db.Column(db.Integer, db.ForeignKey('stock_item.id'), nullable=False)
    quantity_used = db.Column(db.Integer, nullable=False)

    # Relação para acessar o item de estoque facilmente a partir deste registro
    item = db.relationship('StockItem')

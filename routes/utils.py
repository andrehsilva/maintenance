import pytz
from datetime import datetime
from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user

# Importe os modelos e o db para a função notify_admins
from models import User, Notification
from extensions import db

# Fuso horário padrão
FUSO_HORARIO_SP = pytz.timezone('America/Sao_Paulo')

def format_datetime_local(utc_datetime, fmt=None):
    """
    Filtro Jinja para converter uma data UTC (ciente ou ingênua) para o fuso de SP.
    """
    if not utc_datetime:
        return ""

    if utc_datetime.tzinfo is None:
        utc_datetime = pytz.utc.localize(utc_datetime)

    local_datetime = utc_datetime.astimezone(FUSO_HORARIO_SP)
    
    if fmt:
        return local_datetime.strftime(fmt)
    
    return local_datetime.strftime('%d/%m/%Y às %H:%M')


def admin_required(f):
    """
    Decorator que restringe o acesso de uma rota apenas para usuários
    com a função (role) 'admin'.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Acesso restrito a administradores.', 'danger')
            return redirect(url_for('core.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def notify_admins(message, url, excluded_user_id=None):
    """Cria uma notificação para todos os administradores."""
    admins = User.query.filter_by(role='admin').all()
    for admin in admins:
        if admin.id != excluded_user_id:
            notif = Notification(user_id=admin.id, message=message, url=url)
            db.session.add(notif)
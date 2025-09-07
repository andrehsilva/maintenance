"""
routes/time_clock.py

Módulo para registro de ponto eletrônico dos técnicos.
"""
from datetime import datetime, date
from flask import (Blueprint, render_template, request, redirect, url_for, flash)
from flask_login import login_required, current_user

from models import TimeClock
from extensions import db
from .utils import FUSO_HORARIO_SP

time_clock_bp = Blueprint('time_clock', __name__, template_folder='templates')


@time_clock_bp.route('/time-clock', methods=['GET'])
@login_required
def time_clock_page():
    """Página para o técnico registrar seu ponto."""
    today = date.today()
    todays_record = TimeClock.query.filter_by(user_id=current_user.id, date=today).first()
    return render_template('time_clock.html', record=todays_record, today=today)


@time_clock_bp.route('/time-clock/register', methods=['POST'])
@login_required
def register_time_clock():
    """Registra uma entrada ou saída no ponto."""
    action = request.form.get('action')
    today = date.today()
    
    record = TimeClock.query.filter_by(user_id=current_user.id, date=today).first()
    if not record:
        record = TimeClock(user_id=current_user.id, date=today)
        db.session.add(record)

    now = datetime.now(FUSO_HORARIO_SP)
    message = "Ação inválida ou fora de ordem."
    success = False

    if action == 'morning_in' and not record.morning_check_in:
        record.morning_check_in = now
        message = f"Entrada da manhã registrada às {now.strftime('%H:%M')}."
        success = True
    elif action == 'morning_out' and record.morning_check_in and not record.morning_check_out:
        record.morning_check_out = now
        message = f"Saída da manhã registrada às {now.strftime('%H:%M')}."
        success = True
    elif action == 'afternoon_in' and record.morning_check_out and not record.afternoon_check_in:
        record.afternoon_check_in = now
        message = f"Entrada da tarde registrada às {now.strftime('%H:%M')}."
        success = True
    elif action == 'afternoon_out' and record.afternoon_check_in and not record.afternoon_check_out:
        record.afternoon_check_out = now
        message = f"Saída da tarde registrada às {now.strftime('%H:%M')}."
        success = True
    
    try:
        db.session.commit()
        flash(message, 'success' if success else 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao registrar ponto: {e}", 'danger')

    return redirect(url_for('time_clock.time_clock_page'))
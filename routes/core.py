"""
routes/core.py

Rotas centrais da aplicação, como dashboard, landing page e configurações.
"""
from flask import (Blueprint, render_template, request, redirect, url_for, flash)
from flask_login import login_required, current_user
from math import ceil

from models import Equipment, Setting
from extensions import db
from .utils import admin_required

core_bp = Blueprint('core', __name__, template_folder='templates')


@core_bp.route('/')
def index():
    """Página inicial/landing page ou redirecionamento para o dashboard."""
    if current_user.is_authenticated:
        return redirect(url_for('core.dashboard'))
    return render_template('landing_page.html')


@core_bp.route('/dashboard')
@login_required
def dashboard():
    """Painel principal com estatísticas e equipamentos."""
    status_filter = request.args.get('status')
    page = request.args.get('page', 1, type=int)
    per_page = 10

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

    total_items = len(equipments_to_display)
    start = (page - 1) * per_page
    end = start + per_page
    items = equipments_to_display[start:end]

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


@core_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_settings():
    """Página de configurações do sistema."""
    if request.method == 'POST':
        try:
            new_days_str = request.form.get('warning_days')
            if new_days_str:
                setting_days = db.session.get(Setting, 'maintenance_warning_days') or Setting(key='maintenance_warning_days')
                setting_days.value = str(int(new_days_str))
                db.session.add(setting_days)

            whatsapp_template_str = request.form.get('whatsapp_template')
            if whatsapp_template_str is not None:
                setting_template = db.session.get(Setting, 'whatsapp_message_template') or Setting(key='whatsapp_message_template')
                setting_template.value = whatsapp_template_str
                db.session.add(setting_template)

            db.session.commit()
            flash('Configurações salvas com sucesso!', 'success')

        except (ValueError, TypeError) as e:
            db.session.rollback()
            flash(f'Erro nos dados fornecidos: {str(e)}', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao salvar configurações: {str(e)}', 'danger')

        return redirect(url_for('core.manage_settings'))

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
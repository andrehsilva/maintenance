"""
routes/core.py

Rotas centrais da aplicação, como dashboard, landing page e configurações.
"""
from flask import (Blueprint, render_template, request, redirect, url_for, flash)
from flask_login import login_required, current_user
from math import ceil

from datetime import datetime
from sqlalchemy import extract, func

from models import Equipment, Setting, Client, MaintenanceHistory, Expense
from extensions import db
from .utils import admin_required

core_bp = Blueprint('core', __name__, template_folder='templates')


@core_bp.route('/')
def index():
    """Página inicial/landing page ou redirecionamento para o dashboard."""
    if current_user.is_authenticated:
        return redirect(url_for('core.dashboard'))
    return render_template('landing_page.html')


# Em routes/core.py

# Não se esqueça de importar o Client no topo do arquivo
from models import Equipment, Setting, Client
# ... (outras importações)


@core_bp.route('/dashboard')
@login_required
def dashboard():
    # --- Lógica de Filtros (já existente) ---
    status_filter = request.args.get('status')
    client_id = request.args.get('client_id', type=int)
    page = request.args.get('page', 1, type=int)
    per_page = 10

    if current_user.role == 'admin':
        base_query = Equipment.query.filter_by(is_archived=False)
    else:
        base_query = Equipment.query.filter_by(user_id=current_user.id, is_archived=False)

    if client_id:
        base_query = base_query.filter_by(client_id=client_id)

    all_user_equipments = base_query.order_by(Equipment.next_maintenance_date).all()
    stats = {
        'total': len(all_user_equipments),
        'em_dia': len([e for e in all_user_equipments if e.status == 'Em dia']),
        'proximo': len([e for e in all_user_equipments if e.status == 'Próximo do vencimento']),
        'vencido': len([e for e in all_user_equipments if e.status == 'Vencido'])
    }
    # ... (O resto da sua lógica de filtragem e paginação continua aqui) ...
    # ... (Copiado para ser breve, mantenha sua lógica original) ...
    equipments_to_display = all_user_equipments # Simplicidade para o exemplo
    items = equipments_to_display[0:per_page]
    class Pagination:
        def __init__(self, items, page, per_page, total):
            self.items, self.page, self.per_page, self.total = items, page, per_page, total
            self.pages = 1
    equipments = Pagination(items, 1, per_page, len(items))


    # --- NOVO: Cálculo dos Indicadores Mensais (KPIs) ---
    today = datetime.utcnow()
    current_month = today.month
    current_year = today.year
    
    # Base de query para o mês atual
    maintenance_this_month_query = MaintenanceHistory.query.filter(
        extract('year', MaintenanceHistory.maintenance_date) == current_year,
        extract('month', MaintenanceHistory.maintenance_date) == current_month
    )
    
    expenses_this_month_query = Expense.query.filter(
        extract('year', Expense.date) == current_year,
        extract('month', Expense.date) == current_month
    )

    # Dicionário com os KPIs calculados
    monthly_kpis = {
        'maintenances_count': maintenance_this_month_query.count(),
        
        'revenue': maintenance_this_month_query.with_entities(func.sum(MaintenanceHistory.cost)).scalar() or 0,
        
        'expenses': expenses_this_month_query.with_entities(func.sum(Expense.value)).scalar() or 0,
        
        'preventive_count': maintenance_this_month_query.filter(MaintenanceHistory.category == 'Manutenção Preventiva').count(),
        
        'corrective_count': maintenance_this_month_query.filter(MaintenanceHistory.category == 'Manutenção Corretiva').count()
    }

    clients = Client.query.filter_by(is_archived=False).order_by(Client.name).all()

    return render_template(
        'dashboard.html',
        equipments=equipments,
        stats=stats,
        active_filter=status_filter,
        clients=clients,
        filters=request.args,
        monthly_kpis=monthly_kpis # Passa os novos indicadores para o template
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
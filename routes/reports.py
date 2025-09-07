"""
routes/reports.py

Módulo central para todos os relatórios e exportações de dados do sistema.
Acessível apenas por administradores.
"""
import io
import pandas as pd
from datetime import datetime
from flask import (Blueprint, render_template, request, url_for, flash, send_file, redirect)
from flask_login import login_required
from sqlalchemy import desc, extract
from sqlalchemy.orm import joinedload

# Importações do projeto
from models import (Client, Equipment, MaintenanceHistory, User, Expense, TimeClock,
                    StockItem, MaintenancePartUsed)
from extensions import db
from .utils import admin_required, FUSO_HORARIO_SP, format_datetime_local

# --- Configurações do Blueprint ---
reports_bp = Blueprint('reports', __name__, template_folder='templates')

# --- Constantes do Módulo ---
STOCK_CATEGORIES = sorted(['Peças de Reposição', 'Ferramentas', 'Consumíveis', 'EPIs', 'Material de Limpeza', 'Geral'])
EXPENSE_CATEGORIES = ['Alimentação', 'Gasolina', 'Pedágio', 'Lanche', 'Gastos Diversos']


# --- RELATÓRIOS FINANCEIROS ---

@reports_bp.route('/reports/financial')
@login_required
@admin_required
def financial_report():
    """Página do relatório financeiro de manutenções."""
    clients = Client.query.filter_by(is_archived=False).order_by(Client.name).all()
    equipments = Equipment.query.filter_by(is_archived=False).order_by(Equipment.code).all()
    client_id = request.args.get('client_id', type=int)
    equipment_id = request.args.get('equipment_id', type=int)
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    query = db.session.query(MaintenanceHistory).join(Equipment)
    if client_id: query = query.filter(Equipment.client_id == client_id)
    if equipment_id: query = query.filter(MaintenanceHistory.equipment_id == equipment_id)
    if start_date_str: query = query.filter(MaintenanceHistory.maintenance_date >= datetime.strptime(start_date_str, '%Y-%m-%d').date())
    if end_date_str: query = query.filter(MaintenanceHistory.maintenance_date <= datetime.strptime(end_date_str, '%Y-%m-%d').date())

    records = query.order_by(desc(MaintenanceHistory.maintenance_date)).all()
    total_cost = sum(r.cost for r in records if r.cost is not None)

    return render_template('financial_report.html', clients=clients, equipments=equipments,
                           records=records, total_cost=total_cost, filters=request.args)

@reports_bp.route('/export/financial')
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
            joinedload(MaintenanceHistory.equipment).joinedload(Equipment.client))
        if client_id: query = query.filter(Equipment.client_id == client_id)
        if equipment_id: query = query.filter(MaintenanceHistory.equipment_id == equipment_id)
        if start_date_str: query = query.filter(MaintenanceHistory.maintenance_date >= datetime.strptime(start_date_str, '%Y-%m-%d').date())
        if end_date_str: query = query.filter(MaintenanceHistory.maintenance_date <= datetime.strptime(end_date_str, '%Y-%m-%d').date())

        records = query.order_by(desc(MaintenanceHistory.maintenance_date)).all()
        data_for_df = [{'Data': r.maintenance_date.strftime('%d/%m/%Y'), 'Equipamento (Código)': r.equipment.code,
                        'Equipamento (Modelo)': r.equipment.model, 'Cliente': r.equipment.client.name,
                        'Custo (R$)': float(r.cost) if r.cost else 0.0} for r in records]

        df = pd.DataFrame(data_for_df)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Financeiro')
        output.seek(0)

        timestamp = datetime.now(FUSO_HORARIO_SP).strftime("%Y-%m-%d")
        return send_file(output, as_attachment=True, download_name=f'relatorio_financeiro_{timestamp}.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        flash(f"Erro ao gerar o relatório Excel: {e}", "danger")
        return redirect(url_for('reports.financial_report'))


# --- RELATÓRIOS DE DESPESAS ---

@reports_bp.route('/reports/expenses')
@login_required
@admin_required
def expense_report():
    """Página para o admin visualizar e filtrar todas as despesas."""
    technicians = User.query.filter_by(role='technician').order_by(User.username).all()

    tech_id = request.args.get('technician_id', type=int)
    category = request.args.get('category')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    query = Expense.query
    if tech_id: query = query.filter(Expense.user_id == tech_id)
    if category: query = query.filter(Expense.category == category)
    if start_date_str: query = query.filter(Expense.date >= datetime.strptime(start_date_str, '%Y-%m-%d').date())
    if end_date_str: query = query.filter(Expense.date <= datetime.strptime(end_date_str, '%Y-%m-%d').date())

    records = query.order_by(desc(Expense.date), Expense.user_id).all()
    total_value = sum(r.value for r in records if r.value is not None)

    return render_template('expense_report.html', technicians=technicians, records=records,
                           total_value=total_value, categories=EXPENSE_CATEGORIES, filters=request.args)

@reports_bp.route('/export/expenses')
@login_required
@admin_required
def export_expenses():
    """Gera um arquivo Excel com o relatório de despesas filtrado."""
    try:
        tech_id = request.args.get('technician_id', type=int)
        category = request.args.get('category')
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        query = Expense.query.options(joinedload(Expense.technician))
        if tech_id: query = query.filter(Expense.user_id == tech_id)
        if category: query = query.filter(Expense.category == category)
        if start_date_str: query = query.filter(Expense.date >= datetime.strptime(start_date_str, '%Y-%m-%d').date())
        if end_date_str: query = query.filter(Expense.date <= datetime.strptime(end_date_str, '%Y-%m-%d').date())

        records = query.order_by(desc(Expense.date), Expense.user_id).all()

        data_for_df = [{'Data': r.date.strftime('%d/%m/%Y'), 'Técnico': r.technician.username,
                        'Categoria': r.category, 'Descrição': r.description,
                        'Valor (R$)': float(r.value)} for r in records]

        df = pd.DataFrame(data_for_df)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Despesas')
        output.seek(0)

        timestamp = datetime.now(FUSO_HORARIO_SP).strftime("%Y-%m-%d")
        return send_file(output, as_attachment=True, download_name=f'relatorio_despesas_{timestamp}.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        flash(f"Erro ao gerar o relatório Excel: {e}", "danger")
        return redirect(url_for('reports.expense_report'))


# --- RELATÓRIOS DE PONTO ELETRÔNICO ---

@reports_bp.route('/reports/time-clock')
@login_required
@admin_required
def time_clock_report():
    """Exibe o relatório de ponto para o admin."""
    technicians = User.query.filter(User.role != 'admin').order_by(User.username).all()
    tech_id = request.args.get('technician_id', type=int)
    month_str = request.args.get('month', datetime.now().strftime('%Y-%m'))

    try:
        year, month = map(int, month_str.split('-'))
    except ValueError:
        year, month = datetime.now().year, datetime.now().month
        month_str = f"{year}-{month:02d}"

    query = TimeClock.query
    if tech_id:
        query = query.filter(TimeClock.user_id == tech_id)

    query = query.filter(extract('year', TimeClock.date) == year, extract('month', TimeClock.date) == month)
    
    records = query.order_by(desc(TimeClock.date), TimeClock.user_id).all()

    # Início da correção
    total_seconds = 0
    for record in records:
        if record.morning_check_in and record.morning_check_out:
            total_seconds += (record.morning_check_out - record.morning_check_in).total_seconds()
        if record.afternoon_check_in and record.afternoon_check_out:
            total_seconds += (record.afternoon_check_out - record.afternoon_check_in).total_seconds()
    # Fim da correção
    
    total_hours = f"{(total_seconds / 3600):.2f}".replace('.', ',')

    return render_template('time_clock_report.html', technicians=technicians, records=records,
                           total_hours=total_hours, filters=request.args, month_filter=month_str)

@reports_bp.route('/export/time-clock')
@login_required
@admin_required
def export_time_clock():
    """Gera um arquivo Excel com o relatório de ponto filtrado."""
    try:
        tech_id = request.args.get('technician_id', type=int)
        month_str = request.args.get('month', datetime.now().strftime('%Y-%m'))
        year, month = map(int, month_str.split('-'))

        query = TimeClock.query.options(joinedload(TimeClock.technician))
        if tech_id: query = query.filter(TimeClock.user_id == tech_id)
        query = query.filter(extract('year', TimeClock.date) == year, extract('month', TimeClock.date) == month)
        records = query.order_by(desc(TimeClock.date), TimeClock.user_id).all()

        data_for_df = [{
            'Data': r.date.strftime('%d/%m/%Y'), 'Técnico': r.technician.username,
            'Entrada Manhã': format_datetime_local(r.morning_check_in, '%H:%M') if r.morning_check_in else '-',
            'Saída Manhã': format_datetime_local(r.morning_check_out, '%H:%M') if r.morning_check_out else '-',
            'Entrada Tarde': format_datetime_local(r.afternoon_check_in, '%H:%M') if r.afternoon_check_in else '-',
            'Saída Tarde': format_datetime_local(r.afternoon_check_out, '%H:%M') if r.afternoon_check_out else '-',
            'Total Horas': r.total_hours
        } for r in records]

        df = pd.DataFrame(data_for_df)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name=f'Ponto_{month_str}')
        output.seek(0)

        timestamp = datetime.now(FUSO_HORARIO_SP).strftime("%Y-%m-%d")
        return send_file(output, as_attachment=True, download_name=f'relatorio_ponto_{month_str}_{timestamp}.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        flash(f"Erro ao gerar o relatório Excel: {e}", "danger")
        return redirect(url_for('reports.time_clock_report'))


# --- RELATÓRIOS DE ESTOQUE ---

@reports_bp.route('/reports/stock-movement')
@login_required
@admin_required
def stock_movement_report():
    """Relatório de movimentação de estoque."""
    item_id = request.args.get('item_id', type=int)
    category_filter = request.args.get('category')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    items_query = StockItem.query
    if category_filter:
        items_query = items_query.filter(StockItem.category == category_filter)
    items = items_query.order_by(StockItem.name).all()

    outgoing_query = db.session.query(
        MaintenancePartUsed, MaintenanceHistory, Equipment, Client
    ).select_from(MaintenancePartUsed).join(
        MaintenanceHistory, MaintenancePartUsed.maintenance_history_id == MaintenanceHistory.id
    ).join(
        Equipment, MaintenanceHistory.equipment_id == Equipment.id
    ).join(
        Client, Equipment.client_id == Client.id
    ).join(
        StockItem, MaintenancePartUsed.stock_item_id == StockItem.id
    )

    if item_id: outgoing_query = outgoing_query.filter(MaintenancePartUsed.stock_item_id == item_id)
    if category_filter: outgoing_query = outgoing_query.filter(StockItem.category == category_filter)
    if start_date_str: outgoing_query = outgoing_query.filter(MaintenanceHistory.maintenance_date >= datetime.strptime(start_date_str, '%Y-%m-%d').date())
    if end_date_str: outgoing_query = outgoing_query.filter(MaintenanceHistory.maintenance_date <= datetime.strptime(end_date_str, '%Y-%m-%d').date())

    all_movements = outgoing_query.order_by(desc(MaintenanceHistory.maintenance_date)).all()

    outgoing_movements_data = []
    for mov in all_movements:
        outgoing_movements_data.append({
            'maintenance_date': mov.MaintenanceHistory.maintenance_date,
            'item_name': mov.MaintenancePartUsed.item.name, # Acesso direto ao nome do item
            'quantity_used': mov.MaintenancePartUsed.quantity_used,
            'equipment_code': mov.Equipment.code,
            'client_name': mov.Client.name
        })

    total_withdrawals = sum(mov['quantity_used'] for mov in outgoing_movements_data)

    return render_template('stock_movement_report.html',
                         items=items,
                         outgoing_movements=outgoing_movements_data,
                         total_withdrawals=total_withdrawals,
                         categories=STOCK_CATEGORIES,
                         filters=request.args)

@reports_bp.route('/export/stock-movement')
@login_required
@admin_required
def export_stock_movement():
    """Gera um arquivo Excel com a movimentação e o status atual do estoque."""
    try:
        item_id = request.args.get('item_id', type=int)
        category_filter = request.args.get('category')
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        # --- ABA DE MOVIMENTAÇÕES ---
        outgoing_query = db.session.query(
            MaintenancePartUsed
        ).join(MaintenanceHistory).join(StockItem)
        
        if item_id: outgoing_query = outgoing_query.filter(MaintenancePartUsed.stock_item_id == item_id)
        if category_filter: outgoing_query = outgoing_query.filter(StockItem.category == category_filter)
        if start_date_str: outgoing_query = outgoing_query.filter(MaintenanceHistory.maintenance_date >= datetime.strptime(start_date_str, '%Y-%m-%d').date())
        if end_date_str: outgoing_query = outgoing_query.filter(MaintenanceHistory.maintenance_date <= datetime.strptime(end_date_str, '%Y-%m-%d').date())
        
        movements = outgoing_query.order_by(desc(MaintenanceHistory.maintenance_date)).all()

        movements_data = [{
            'Data': mov.maintenance_record.maintenance_date.strftime('%d/%m/%Y'),
            'Item': mov.item.name,
            'Categoria': mov.item.category,
            'Quantidade Retirada': mov.quantity_used,
            'Equipamento': mov.maintenance_record.equipment.code,
            'Cliente': mov.maintenance_record.equipment.client.name
        } for mov in movements]
        df_movements = pd.DataFrame(movements_data)

        # --- ABA DE ESTOQUE ATUAL ---
        stock_query = StockItem.query
        if category_filter: stock_query = stock_query.filter(StockItem.category == category_filter)
        all_items = stock_query.order_by(StockItem.name).all()
        
        stock_status_data = []
        for item in all_items:
            status = 'Normal'
            if item.quantity <= item.low_stock_threshold:
                status = 'Crítico'
            elif item.quantity <= item.low_stock_threshold * 2:
                status = 'Atenção'
            
            stock_status_data.append({
                'Item': item.name, 'Categoria': item.category, 'SKU': item.sku,
                'Estoque Atual': item.quantity, 'Nível de Alerta': item.low_stock_threshold,
                'Custo Unitário (R$)': float(item.unit_cost) if item.unit_cost else 0.0,
                'Status': status
            })
        df_stock_status = pd.DataFrame(stock_status_data)

        # --- GERAR O ARQUIVO EXCEL ---
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_stock_status.to_excel(writer, index=False, sheet_name='Estoque Atual')
            df_movements.to_excel(writer, index=False, sheet_name='Movimentações')
        output.seek(0)

        timestamp = datetime.now(FUSO_HORARIO_SP).strftime("%Y-%m-%d")
        return send_file(output, as_attachment=True,
                         download_name=f'relatorio_estoque_{timestamp}.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        flash(f"Erro ao gerar o relatório Excel: {e}", "danger")
        return redirect(url_for('reports.stock_movement_report'))
"""
routes/expenses.py

Módulo para que os usuários (técnicos) gerenciem seus próprios
registros de despesas diárias.
"""
from datetime import datetime, date, timedelta
from flask import (Blueprint, render_template, request, redirect, url_for, flash, abort)
from flask_login import login_required, current_user
from sqlalchemy import func

# Importações do projeto
from models import Expense
from extensions import db

# --- Configurações do Blueprint ---
expenses_bp = Blueprint('expenses', __name__, template_folder='templates')

# --- Constantes do Módulo ---
EXPENSE_CATEGORIES = ['Alimentação', 'Combustível ', 'Pedágio', 'Lanche', 'Gastos Diversos']


@expenses_bp.route('/expenses', methods=['GET', 'POST'])
@login_required
def manage_expenses():
    """
    Página para registrar e visualizar as despesas de um técnico em uma data específica.
    """
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
                return redirect(url_for('expenses.manage_expenses', date=expense_date_str))

            value = float(value_str.replace(',', '.'))

            new_expense = Expense(
                date=expense_date, category=category, value=value,
                description=description, user_id=current_user.id
            )
            db.session.add(new_expense)
            db.session.commit()
            flash('Despesa registrada com sucesso!', 'success')
            return redirect(url_for('expenses.manage_expenses', date=expense_date_str))

        except (ValueError, TypeError):
            flash('O valor informado é inválido. Use um formato como 50.75.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao registrar despesa: {e}', 'danger')

        return redirect(url_for('expenses.manage_expenses', date=selected_date.strftime('%Y-%m-%d')))

    # --- Lógica de Exibição (GET) ---
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

    return render_template('expenses.html',
                           daily_expenses=daily_expenses,
                           categories=EXPENSE_CATEGORIES,
                           selected_date=selected_date,
                           weekly_total=weekly_total,
                           start_of_week=start_of_week,
                           end_of_week=end_of_week,
                           previous_day=previous_day,
                           next_day=next_day)


@expenses_bp.route('/expenses/delete/<int:expense_id>', methods=['POST'])
@login_required
def delete_expense(expense_id):
    """Permite que um usuário delete sua própria despesa (ou um admin delete qualquer uma)."""
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

    # Redireciona de volta para a página de onde veio.
    return redirect(request.referrer or url_for('expenses.manage_expenses'))
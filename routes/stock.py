"""
routes/stock.py

Módulo para administradores gerenciarem o estoque de peças e materiais.
"""
from flask import (Blueprint, render_template, request, redirect, url_for, flash, abort)
from flask_login import login_required

from models import StockItem, MaintenancePartUsed
from extensions import db
from .utils import admin_required

stock_bp = Blueprint('stock', __name__, template_folder='templates')

STOCK_CATEGORIES = sorted(['Peças de Reposição', 'Ferramentas', 'Consumíveis', 'EPIs', 'Material de Limpeza', 'Geral'])


@stock_bp.route('/stock')
@login_required
@admin_required
def stock_list():
    """Exibe a lista de itens em estoque com filtros."""
    category_filter = request.args.get('category')
    query = StockItem.query
    if category_filter:
        query = query.filter(StockItem.category == category_filter)
    items = query.order_by(StockItem.name).all()
    return render_template('stock_list.html', items=items, categories=STOCK_CATEGORIES, filters=request.args)


@stock_bp.route('/stock/item/new', methods=['GET', 'POST'])
@login_required
@admin_required
def add_stock_item():
    """Adiciona um novo item ao estoque."""
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            category = request.form.get('category')

            if not name or not category:
                flash('Nome e Categoria do item são obrigatórios.', 'danger')
                return render_template('stock_form.html', title="Novo Item de Estoque", item=None, categories=STOCK_CATEGORIES, form_data=request.form)
            
            if StockItem.query.filter_by(name=name).first():
                flash('Já existe um item com este nome.', 'warning')
                return render_template('stock_form.html', title="Novo Item de Estoque", item=None, categories=STOCK_CATEGORIES, form_data=request.form)
            
            new_item = StockItem(
                name=name, category=category, sku=request.form.get('sku'),
                description=request.form.get('description'),
                quantity=int(request.form.get('quantity', 0)),
                low_stock_threshold=int(request.form.get('low_stock_threshold', 5)),
                unit_cost=float(request.form.get('unit_cost').replace(',', '.')) if request.form.get('unit_cost') else None,
                requires_tracking=request.form.get('requires_tracking', 'true').lower() == 'true'
            )
            db.session.add(new_item)
            db.session.commit()
            flash(f'Item "{name}" adicionado ao estoque com sucesso!', 'success')
            return redirect(url_for('stock.stock_list'))
            
        except (ValueError, TypeError):
            flash('Valores numéricos inválidos. Verifique Quantidade, Nível de Alerta e Custo.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao adicionar item: {e}', 'danger')
    
    return render_template('stock_form.html', title="Novo Item de Estoque", item=None, categories=STOCK_CATEGORIES, form_data={})


@stock_bp.route('/stock/item/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_stock_item(item_id):
    """Edita um item de estoque existente."""
    item = db.session.get(StockItem, item_id)
    if not item:
        abort(404)
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            category = request.form.get('category')

            if not name or not category:
                flash('Nome e Categoria do item são obrigatórios.', 'danger')
                return render_template('stock_form.html', title="Editar Item", item=item, categories=STOCK_CATEGORIES, form_data=request.form)

            existing_item = StockItem.query.filter(StockItem.name == name, StockItem.id != item_id).first()
            if existing_item:
                flash('Já existe outro item com este nome.', 'warning')
                return render_template('stock_form.html', title="Editar Item", item=item, categories=STOCK_CATEGORIES, form_data=request.form)

            item.name, item.category, item.sku = name, category, request.form.get('sku')
            item.description = request.form.get('description')
            item.quantity = int(request.form.get('quantity', 0))
            item.low_stock_threshold = int(request.form.get('low_stock_threshold', 5))
            item.unit_cost = float(request.form.get('unit_cost').replace(',', '.')) if request.form.get('unit_cost') else None
            item.requires_tracking = request.form.get('requires_tracking', 'true').lower() == 'true'

            db.session.commit()
            flash(f'Item "{name}" atualizado com sucesso!', 'success')
            return redirect(url_for('stock.stock_list'))
            
        except (ValueError, TypeError):
            flash('Valores numéricos inválidos.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar item: {e}', 'danger')
    return render_template('stock_form.html', title="Editar Item", item=item, categories=STOCK_CATEGORIES, form_data=item.__dict__)


@stock_bp.route('/stock/item/delete/<int:item_id>', methods=['POST'])
@login_required
@admin_required
def delete_stock_item(item_id):
    """Exclui um item do estoque."""
    item = db.session.get(StockItem, item_id)
    if not item:
        flash('Item não encontrado.', 'danger')
    elif MaintenancePartUsed.query.filter_by(stock_item_id=item_id).first():
        flash(f'Não é possível excluir o item "{item.name}", pois ele já foi utilizado em manutenções.', 'danger')
    else:
        try:
            db.session.delete(item)
            db.session.commit()
            flash(f'Item "{item.name}" excluído com sucesso.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao excluir item: {e}', 'danger')
    return redirect(url_for('stock.stock_list'))


@stock_bp.route('/stock/manual-adjust/<int:item_id>', methods=['GET', 'POST'])
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

            if adjustment_type == 'add':
                item.quantity += quantity
                flash(f'✅ Adicionadas {quantity} unidades ao estoque de "{item.name}".', 'success')
            elif adjustment_type == 'remove':
                if item.quantity < quantity:
                    flash('❌ Quantidade insuficiente em estoque.', 'danger')
                    return redirect(url_for('stock.manual_stock_adjust', item_id=item_id))
                item.quantity -= quantity
                flash(f'✅ Removidas {quantity} unidades do estoque de "{item.name}".', 'success')

            db.session.commit()
            return redirect(url_for('stock.stock_list'))

        except (ValueError, TypeError):
            flash('❌ Quantidade inválida.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Erro ao ajustar estoque: {e}', 'danger')

    return render_template('manual_stock_adjust.html', item=item)


@stock_bp.route('/stock/quick-adjust/<int:item_id>', methods=['POST'])
@login_required
@admin_required
def quick_stock_adjust(item_id):
    """Ajuste rápido de estoque diretamente da lista."""
    item = db.session.get(StockItem, item_id)
    if not item:
        flash('Item não encontrado.', 'danger')
        return redirect(url_for('stock.stock_list'))

    try:
        adjustment_type = request.form.get('adjustment_type')
        quantity = int(request.form.get('quantity'))

        if adjustment_type == 'add':
            item.quantity += quantity
            flash(f'Adicionadas {quantity} unidades ao estoque de "{item.name}".', 'success')
        elif adjustment_type == 'remove':
            if item.quantity < quantity:
                flash('Quantidade insuficiente em estoque.', 'danger')
                return redirect(url_for('stock.stock_list'))
            item.quantity -= quantity
            flash(f'Removidas {quantity} unidades do estoque de "{item.name}".', 'success')

        db.session.commit()

    except (ValueError, TypeError):
        flash('Quantidade inválida.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao ajustar estoque: {e}', 'danger')

    return redirect(url_for('stock.stock_list'))
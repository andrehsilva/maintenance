"""
routes/users.py

Módulo para administradores gerenciarem os usuários do sistema.
"""
from flask import (Blueprint, render_template, request, redirect, url_for, flash, abort)
from flask_login import login_required, current_user
from sqlalchemy import or_

from models import User, Notification
from extensions import db
from .utils import admin_required

users_bp = Blueprint('users', __name__, template_folder='templates')


@users_bp.route('/users')
@login_required
@admin_required
def user_list():
    """Exibe uma lista de todos os usuários."""
    users = User.query.order_by(User.name).all()
    return render_template('user_list.html', users=users)


@users_bp.route('/user/new', methods=['GET', 'POST'])
@login_required
@admin_required
def create_user():
    """Cria um novo usuário (admin ou técnico)."""
    if request.method == 'POST':
        username = request.form.get('username')
        name = request.form.get('name')
        email = request.form.get('email')
        cpf = request.form.get('cpf')
        password = request.form.get('password')
        role = request.form.get('role')

        if not all([username, name, email, cpf, password, role]):
            flash('Todos os campos marcados com * são obrigatórios.', 'danger')
            return render_template('user_form.html', title="Criar Novo Usuário", user=None, form_data=request.form)

        existing_user = User.query.filter(or_(User.username == username, User.email == email, User.cpf == cpf)).first()
        if existing_user:
            if existing_user.username == username: flash('Este nome de usuário já está em uso.', 'warning')
            elif existing_user.email == email: flash('Este e-mail já está cadastrado.', 'warning')
            elif existing_user.cpf == cpf: flash('Este CPF já está cadastrado.', 'warning')
            return render_template('user_form.html', title="Criar Novo Usuário", user=None, form_data=request.form)
        
        new_user = User(username=username, name=name, email=email, cpf=cpf, role=role, is_active=True)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash(f'Usuário "{name}" criado com sucesso!', 'success')
        return redirect(url_for('users.user_list'))
        
    return render_template('user_form.html', title="Criar Novo Usuário", user=None, form_data={})


@users_bp.route('/user/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    """Edita um usuário existente."""
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
        
    if request.method == 'POST':
        username = request.form.get('username')
        name = request.form.get('name')
        email = request.form.get('email')
        cpf = request.form.get('cpf')
        password = request.form.get('password')
        role = request.form.get('role')

        existing_user = User.query.filter(User.id != user_id, or_(User.username == username, User.email == email, User.cpf == cpf)).first()
        if existing_user:
            if existing_user.username == username: flash('Este nome de usuário já está em uso por outra conta.', 'warning')
            elif existing_user.email == email: flash('Este e-mail já está em uso por outra conta.', 'warning')
            elif existing_user.cpf == cpf: flash('Este CPF já está em uso por outra conta.', 'warning')
            return render_template('user_form.html', title="Editar Usuário", user=user, form_data=request.form)

        user.username, user.name, user.email, user.cpf, user.role = username, name, email, cpf, role
        if password:
            user.set_password(password)
        
        db.session.commit()
        flash(f'Usuário "{name}" atualizado com sucesso!', 'success')
        return redirect(url_for('users.user_list'))

    return render_template('user_form.html', title="Editar Usuário", user=user, form_data=user.__dict__)


@users_bp.route('/user/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    """Exclui um usuário."""
    user_to_delete = db.session.get(User, user_id)
    if not user_to_delete:
        flash('Usuário não encontrado.', 'danger')
        return redirect(url_for('users.user_list'))
    
    if user_to_delete.id == current_user.id:
        flash('Você não pode excluir sua própria conta.', 'danger')
        return redirect(url_for('users.user_list'))
        
    if user_to_delete.equipments:
            flash(f'Não é possível excluir o usuário "{user_to_delete.username}", pois ele está associado a equipamentos.', 'danger')
            return redirect(url_for('users.user_list'))

    db.session.delete(user_to_delete)
    db.session.commit()
    flash(f'Usuário "{user_to_delete.username}" excluído com sucesso.', 'success')
    return redirect(url_for('users.user_list'))


@users_bp.route('/user/approve/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def approve_user(user_id):
    """Aprova o cadastro de um novo usuário."""
    user_to_approve = db.session.get(User, user_id)
    if user_to_approve:
        user_to_approve.is_active = True
        
        msg = "Sua conta foi aprovada! Agora você já pode fazer o login no sistema."
        user_notif = Notification(user_id=user_to_approve.id, message=msg, url=url_for('auth.login'))
        db.session.add(user_notif)
        
        db.session.commit()
        flash(f'Usuário "{user_to_approve.username}" aprovado com sucesso.', 'success')
    else:
        flash('Usuário não encontrado.', 'danger')
        
    return redirect(url_for('users.user_list'))
"""
routes/auth.py

Rotas para autenticação de usuários: login, registro e logout.
"""
from flask import (Blueprint, render_template, request, redirect, url_for, flash)
from flask_login import login_user, logout_user, current_user, login_required
from sqlalchemy import or_

from models import User, Notification
from extensions import db
from .utils import notify_admins

auth_bp = Blueprint('auth', __name__, template_folder='templates')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Página de login."""
    if current_user.is_authenticated:
        return redirect(url_for('core.dashboard'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()

        if user and user.check_password(request.form.get('password')):
            if not user.is_active:
                flash('Sua conta ainda não foi aprovada por um administrador.', 'warning')
                return redirect(url_for('auth.login'))

            login_user(user)
            return redirect(url_for('core.dashboard'))
        else:
            flash('Usuário ou senha inválidos.', 'danger')

    return render_template('login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Página de registro de novos usuários."""
    if current_user.is_authenticated:
        return redirect(url_for('core.dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        name = request.form.get('name')
        email = request.form.get('email')
        cpf = request.form.get('cpf')
        password = request.form.get('password')

        if not all([username, name, email, cpf, password]):
                flash('Todos os campos são obrigatórios.', 'danger')
                return redirect(url_for('auth.register'))

        existing_user = User.query.filter(
            or_(User.username == username, User.email == email, User.cpf == cpf)
        ).first()
        if existing_user:
            if existing_user.username == username: flash('Este nome de usuário já existe.', 'warning')
            elif existing_user.email == email: flash('Este e-mail já está cadastrado.', 'warning')
            elif existing_user.cpf == cpf: flash('Este CPF já está cadastrado.', 'warning')
            return redirect(url_for('auth.register'))

        is_first_user = User.query.count() == 0
        role = 'admin' if is_first_user else 'technician'
        
        new_user = User(
            username=username, name=name, email=email, cpf=cpf,
            role=role, is_active=is_first_user
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        if is_first_user:
            flash('Conta de administrador criada com sucesso! Faça o login.', 'success')
        else:
            msg = f"Novo usuário '{name}' se registrou e aguarda aprovação."
            # Lembre-se que o url_for aqui deve apontar para a rota do blueprint de usuários
            notify_admins(msg, url_for('users.user_list'))
            db.session.commit()
            flash('Conta criada com sucesso! Aguardando aprovação do administrador.', 'info')

        return redirect(url_for('auth.login'))

    return render_template('register.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """Rota de logout."""
    logout_user()
    flash('Você saiu do sistema.', 'success')
    return redirect(url_for('auth.login'))
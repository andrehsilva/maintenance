"""
routes/clients.py

Este módulo contém todas as rotas relacionadas ao gerenciamento de clientes,
utilizando um Flask Blueprint.
"""

import re
from flask import (Blueprint, render_template, request, redirect, url_for, flash, abort)
from flask_login import login_required, current_user
from models import Client, User, Notification, SchedulingLink # Adicione SchedulingLink


# Importa os modelos e a instância do banco de dados das extensões
from models import Client, User, Notification
from extensions import db

# Importa o decorator de permissão do arquivo de utilitários
from .utils import admin_required


# Criação do Blueprint para as rotas de clientes
clients_bp = Blueprint('clients', __name__, template_folder='templates')


@clients_bp.route('/clients')
@login_required
@admin_required
def client_list():
    """Exibe a lista de clientes ativos."""
    clients = Client.query.filter_by(is_archived=False).order_by(Client.name).all()
    return render_template('client_list.html', clients=clients)


@clients_bp.route('/client/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_client():
    """Cria um novo cliente."""
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')

        if phone:
            cleaned_phone = re.sub(r'\D', '', phone)
            if not re.match(r'^\d{10,11}$', cleaned_phone):
                flash('O número de telefone informado é inválido.', 'danger')
                return render_template('client_form.html', title="Novo Cliente", client=None)

        if Client.query.filter_by(name=name).first():
            flash('Já existe um cliente com este nome.', 'warning')
        else:
            client = Client(
                name=name, address=request.form.get('address'),
                contact_person=request.form.get('contact_person'),
                phone=phone
            )
            db.session.add(client)
            db.session.commit()
            flash('Cliente cadastrado com sucesso!', 'success')
            return redirect(url_for('clients.client_list'))
            
    return render_template('client_form.html', title="Novo Cliente", client=None)


@clients_bp.route('/client/edit/<int:client_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_client(client_id):
    """Edita um cliente existente."""
    client = db.session.get(Client, client_id)
    if not client:
        abort(404)
        
    if request.method == 'POST':
        phone = request.form.get('phone')

        if phone:
            cleaned_phone = re.sub(r'\D', '', phone)
            if not re.match(r'^\d{10,11}$', cleaned_phone):
                flash('O número de telefone informado é inválido.', 'danger')
                return render_template('client_form.html', title="Editar Cliente", client=client)

        client.name, client.address = request.form.get('name'), request.form.get('address')
        client.contact_person = request.form.get('contact_person')
        client.phone = phone
        db.session.commit()
        
        msg = f"O cliente '{client.name}' foi atualizado por {current_user.username}."
        admins = User.query.filter_by(role='admin').all()
        for admin in admins:
            if admin.id != current_user.id:
                notif = Notification(user_id=admin.id, message=msg, url=url_for('clients.client_list'))
                db.session.add(notif)
        db.session.commit()
        
        flash('Cliente atualizado com sucesso!', 'success')
        return redirect(url_for('clients.client_list'))

    return render_template('client_form.html', title="Editar Cliente", client=client)


@clients_bp.route('/client/archive/<int:client_id>', methods=['POST'])
@login_required
@admin_required
def toggle_archive_client(client_id):
    """Arquiva ou restaura um cliente."""
    client = db.session.get(Client, client_id)
    if client:
        client.is_archived = not client.is_archived
        db.session.commit()
        flash(f'Cliente "{client.name}" {"arquivado" if client.is_archived else "restaurado"} com sucesso.', 'success')
    else:
        flash('Cliente não encontrado.', 'danger')

    return redirect(request.referrer or url_for('clients.client_list'))


@clients_bp.route('/clients/archived')
@login_required
@admin_required
def archived_clients():
    """Exibe a lista de clientes arquivados."""
    archived = Client.query.filter_by(is_archived=True).order_by(Client.name).all()
    return render_template('archived_clients.html', clients=archived)



@clients_bp.route('/client/<int:client_id>/generate-link', methods=['POST'])
@login_required
@admin_required
def generate_schedule_link(client_id):
    client = db.session.get(Client, client_id)
    if not client:
        flash('Cliente não encontrado.', 'danger')
        return redirect(url_for('clients.client_list'))
    
    # Invalida links antigos para este cliente (opcional, mas recomendado)
    SchedulingLink.query.filter_by(client_id=client_id, is_used=False).update({'is_used': True})

    # Cria o novo link
    purpose = request.form.get('purpose', f'Agendamento para {client.name}')
    new_link = SchedulingLink(client_id=client_id, purpose=purpose)
    db.session.add(new_link)
    db.session.commit()

    # Gera a URL completa para o admin copiar
    public_url = url_for('schedule.public_schedule_page', token=new_link.token, _external=True)
    
    flash(f'Link gerado com sucesso! Envie para o cliente: {public_url}', 'success')
    return redirect(url_for('clients.client_list'))
"""
routes/notifications.py

Módulo para o gerenciamento de notificações do sistema, incluindo a leitura
e o painel de envio de lembretes de manutenção via WhatsApp.
"""

import re
from urllib.parse import quote

from flask import (Blueprint, render_template, request, redirect, url_for, flash)
from flask_login import login_required, current_user

# Importações do projeto
from models import Notification, Setting, Equipment
from extensions import db
from .utils import admin_required

# --- Configurações do Blueprint ---
notifications_bp = Blueprint('notifications', __name__, template_folder='templates')


@notifications_bp.route('/notifications/read/<int:notification_id>')
@login_required
def read_notification(notification_id):
    """Marca uma notificação como lida e redireciona para a URL de destino."""
    notification = db.session.get(Notification, notification_id)
    
    # Garante que o usuário só pode ler as próprias notificações
    if notification and notification.user_id == current_user.id:
        notification.is_read = True
        db.session.commit()

    # Se a notificação tiver uma URL, redireciona para ela. Senão, para o painel principal.
    return redirect(notification.url or url_for('core.dashboard'))


@notifications_bp.route('/notifications/whatsapp')
@login_required
@admin_required
def whatsapp_notifications():
    """Exibe o painel com links pré-formatados para enviar lembretes no WhatsApp."""
    try:
        # Busca o template da mensagem no banco de dados
        template_setting = db.session.get(Setting, 'whatsapp_message_template')
        default_template = (
            "Olá, {client_name}! Gostaríamos de lembrar sobre a manutenção do seu equipamento "
            "'{equipment_model} ({equipment_code})', agendada para o dia {maintenance_date}."
        )
        message_template = template_setting.value if template_setting else default_template
        
        all_active_equipments = Equipment.query.filter_by(is_archived=False).all()
        
        # Filtra na aplicação os equipamentos que estão próximos do vencimento
        due_equipments = [eq for eq in all_active_equipments if eq.status == 'Próximo do vencimento']
        
        notifications_list = []

        for equipment in due_equipments:
            if not equipment.client or not equipment.client.phone:
                continue

            # Limpa o número de telefone, deixando apenas dígitos
            cleaned_phone = re.sub(r'\D', '', equipment.client.phone)
            
            # Monta a mensagem usando o template do banco de dados
            message = message_template.format(
                client_name=(equipment.client.contact_person or equipment.client.name),
                equipment_model=equipment.model,
                equipment_code=equipment.code,
                maintenance_date=equipment.next_maintenance_date.strftime('%d/%m/%Y')
            )
            
            notifications_list.append({
                'equipment': equipment,
                # Codifica a mensagem para ser usada em uma URL e cria o link do WhatsApp
                'whatsapp_link': f"https://wa.me/55{cleaned_phone}?text={quote(message)}"
            })

        return render_template('whatsapp_notifications.html', notifications_list=notifications_list)
        
    except Exception as e:
        flash(f"Erro ao carregar o painel de notificações: {e}", "danger")
        return redirect(url_for('core.dashboard'))
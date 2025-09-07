"""
routes/leads.py

Módulo para captura e gerenciamento de leads (potenciais clientes).
Contém as rotas públicas e a área de visualização para administradores.
"""

from flask import (Blueprint, render_template, request, url_for, jsonify)
from flask_login import login_required
from sqlalchemy import or_, desc

# Importações do projeto
from models import Lead
from extensions import db
from .utils import admin_required #, notify_admins - pode ser descomentado se quiser notificar

# --- Configurações do Blueprint ---
leads_bp = Blueprint('leads', __name__, template_folder='templates')


@leads_bp.route('/quero-uma-demonstracao')
def lead_form():
    """Exibe a página com o formulário de interesse (landing page)."""
    return render_template('lead_form.html')


@leads_bp.route('/politica-de-privacidade')
def privacy_policy():
    """Exibe a página da política de privacidade."""
    return render_template('politica-de-privacidade.html')


@leads_bp.route('/lead/submit', methods=['POST'])
def submit_lead():
    """Recebe os dados do formulário, salva no banco e retorna um JSON."""
    try:
        nome = request.form.get('nome')
        empresa = request.form.get('empresa')
        whatsapp = request.form.get('whatsapp')
        email = request.form.get('email')

        if not all([nome, empresa, whatsapp, email]):
            return jsonify({'status': 'error', 'message': 'Todos os campos são obrigatórios.'}), 400

        # Verifica se o e-mail OU o whatsapp já existem no banco de dados
        existing_lead = Lead.query.filter(
            or_(Lead.email == email, Lead.whatsapp == whatsapp)
        ).first()

        if existing_lead:
            # Se o lead já existe, retorna sucesso para o front-end, mas não cria dados duplicados.
            return jsonify({'status': 'success', 'message': 'Usuário já cadastrado.'})

        # Se não existir, cria um novo lead
        new_lead = Lead(
            nome=nome,
            empresa=empresa,
            whatsapp=whatsapp,
            email=email
        )
        db.session.add(new_lead)

        # Descomente a linha abaixo para notificar os administradores sobre novos leads
        # notify_admins(f"Novo lead: '{nome}' da empresa '{empresa}'.", url_for('leads.list_leads'))

        db.session.commit()

        return jsonify({'status': 'success', 'message': 'Dados recebidos com sucesso!'})

    except Exception as e:
        db.session.rollback()
        # Em um ambiente de produção, seria ideal logar o erro `e`
        print(f"Erro ao salvar lead: {e}")
        return jsonify({'status': 'error', 'message': 'Ocorreu um erro interno.'}), 500


@leads_bp.route('/leads')
@login_required
@admin_required
def list_leads():
    """Exibe a lista paginada de leads capturados para administradores."""
    page = request.args.get('page', 1, type=int)
    per_page = 15

    pagination = Lead.query.order_by(desc(Lead.created_at)).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template('leads.html', pagination=pagination)
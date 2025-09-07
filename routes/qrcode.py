"""
routes/qrcode.py

Módulo para gerar, exibir e servir as páginas públicas acessadas via QR Code.
"""
import io
import qrcode

from flask import (Blueprint, render_template, url_for, abort, send_file)
from flask_login import login_required

# Importações do projeto
from models import Equipment
from .utils import admin_required

# --- Configurações do Blueprint ---
qrcode_bp = Blueprint('qrcode', __name__, template_folder='templates')


@qrcode_bp.route('/public/equipment/<code>')
def public_summary(code):
    """
    Página pública que exibe um resumo do equipamento e seu histórico.
    Esta é a página de destino do QR Code, não requer login.
    """
    equipment = Equipment.query.filter_by(code=code).first()

    # Se o equipamento não for encontrado ou estiver arquivado, retorna um erro 404.
    if not equipment or equipment.is_archived:
        return render_template('public_summary_not_found.html'), 404

    # Carrega o histórico de manutenção para exibição
    history_records = equipment.maintenance_history.all()
    return render_template('public_summary.html', equipment=equipment, history_records=history_records)


@qrcode_bp.route('/equipment/<code>/qrcode')
@login_required
@admin_required
def display_qrcode(code):
    """
    Página interna (para administradores) que exibe o QR Code de um equipamento
    para que possa ser impresso ou salvo.
    """
    equipment = Equipment.query.filter_by(code=code).first()
    if not equipment:
        abort(404)
    return render_template('qrcode_display.html', equipment=equipment)


@qrcode_bp.route('/equipment/<code>/qrcode_image')
def qrcode_image(code):
    """
    Gera e serve a imagem PNG do QR Code sob demanda.
    Esta rota é chamada pela tag <img> na página 'qrcode_display'.
    """
    # Cria a URL completa para a página pública, que será embutida no QR Code.
    # O url_for aponta para a rota 'public_summary' DESTE blueprint.
    public_url = url_for('qrcode.public_summary', code=code, _external=True)

    # Configurações de geração do QR Code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(public_url)
    qr.make(fit=True)

    # Cria a imagem em memória
    img = qr.make_image(fill_color="black", back_color="white")
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)

    # Envia o arquivo de imagem como resposta
    return send_file(img_io, mimetype='image/png')
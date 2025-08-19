# create_user.py (Versão Corrigida)

# 1. Importe a factory 'create_app' em vez da instância 'app'
from app import create_app
# 2. Importe o modelo e a extensão de seus arquivos de origem
from models import User
from extensions import db

def create_user(username, password, role='technician', is_active=False):
    """
    Cria um novo usuário no banco de dados com um papel e status específicos.
    """
    # Cria uma instância da aplicação especificamente para este script
    app = create_app()

    # Usa o contexto da aplicação para interagir com o banco de dados
    with app.app_context():
        # Verifica se o usuário já existe
        if User.query.filter_by(username=username).first():
            print(f"Erro: O usuário '{username}' já existe.")
            return

        # LÓGICA ATUALIZADA: Admins criados por este script são sempre ativos.
        if role == 'admin':
            is_active = True

        # Cria a nova instância de usuário com o campo is_active
        new_user = User(username=username, role=role, is_active=is_active)
        
        # Criptografa a senha
        new_user.set_password(password)
        
        # Adiciona ao banco e salva
        db.session.add(new_user)
        db.session.commit()
        
        status_msg = "ativo" if is_active else "pendente de aprovação"
        print(f"Usuário '{username}' criado com sucesso com o papel de '{role}' e status '{status_msg}'.")

# --- Exemplo de como usar ---
if __name__ == '__main__':
    print("--- Tentando criar usuários ---")
    
    # Exemplo 1: Criando um técnico (começará como inativo/pendente)
    create_user('tecnico', '123456', 'technician')

    # Exemplo 2: Criando um administrador (começará como ativo)
    create_user('andre', '123456', 'admin')
    
    # Exemplo 3 (Opcional): Criando um técnico e já ativando-o
    # create_user('tecnico_ativo', '123456', 'technician', is_active=True)

    print("--- Processo finalizado ---")
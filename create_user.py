# create_user.py (Versão Corrigida)

# 1. Importe a factory 'create_app' em vez da instância 'app'
from app import create_app
# 2. Importe o modelo e a extensão de seus arquivos de origem
from models import User
from extensions import db

def create_user(username, password, role='technician'):
    """
    Cria um novo usuário no banco de dados com um papel específico.
    """
    # 3. Cria uma instância da aplicação especificamente para este script
    app = create_app()

    # 4. Usa o contexto da aplicação para interagir com o banco de dados
    with app.app_context():
        # Verifica se o usuário já existe
        if User.query.filter_by(username=username).first():
            print(f"Erro: O usuário '{username}' já existe.")
            return

        # Cria a nova instância de usuário
        new_user = User(username=username, role=role)
        
        # Criptografa a senha
        new_user.set_password(password) #
        
        # Adiciona ao banco e salva
        db.session.add(new_user)
        db.session.commit()
        
        print(f"Usuário '{username}' criado com sucesso com o papel de '{role}'.")

# --- Exemplo de como usar ---
if __name__ == '__main__':
    print("--- Tentando criar usuários ---")
    
    # Exemplo 1: Criando um técnico
    create_user('tecnico', '123456', 'technician')

    # Exemplo 2: Criando um segundo administrador
    create_user('andre', '123456', 'admin')

    print("--- Processo finalizado ---")
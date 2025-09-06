# create_user.py (Versão Corrigida e Completa)

# 1. Importe os módulos necessários
from app import create_app
from models import User
from extensions import db
from sqlalchemy import or_ # Necessário para a nova validação

def create_user(username, password, name, email, cpf, role='technician', is_active=False):
    """
    Cria um novo usuário no banco de dados com nome, email, cpf, papel e status.
    """
    app = create_app()

    with app.app_context():
        # --- VALIDAÇÃO ATUALIZADA ---
        # Verifica se username, email ou cpf já existem no banco
        existing_user = User.query.filter(
            or_(User.username == username, User.email == email, User.cpf == cpf)
        ).first()

        if existing_user:
            if existing_user.username == username:
                print(f"Erro: O nome de usuário '{username}' já existe.")
            elif existing_user.email == email:
                print(f"Erro: O e-mail '{email}' já está em uso.")
            elif existing_user.cpf == cpf:
                print(f"Erro: O CPF '{cpf}' já está cadastrado.")
            return
        # --- FIM DA VALIDAÇÃO ---

        # Admins criados por este script são sempre ativos.
        if role == 'admin':
            is_active = True

        # --- CRIAÇÃO DO USUÁRIO ATUALIZADA ---
        # Cria a nova instância de usuário com todos os campos novos
        new_user = User(
            username=username,
            name=name,
            email=email,
            cpf=cpf,
            role=role, 
            is_active=is_active
        )
        
        # Criptografa a senha
        new_user.set_password(password)
        
        # Adiciona ao banco e salva
        db.session.add(new_user)
        db.session.commit()
        
        status_msg = "ativo" if is_active else "pendente de aprovação"
        print(f"Usuário '{name}' ({username}) criado com sucesso com o papel de '{role}' e status '{status_msg}'.")

# --- Exemplo de como usar (ATUALIZADO) ---
if __name__ == '__main__':
    print("--- Tentando criar usuários ---")
    
    # Exemplo 1: Criando um técnico (começará como inativo/pendente)
    create_user(
        username='tecnico', 
        password='123456', 
        name='João da Silva', 
        email='joao.silva@empresa.com',
        cpf='111.222.333-44',
        role='technician'
    )

    # Exemplo 2: Criando um administrador (começará como ativo)
    create_user(
        username='andre', 
        password='123456', 
        name='André Rodrigues', 
        email='andre.admin@empresa.com',
        cpf='999.888.777-66',
        role='admin'
    )

    # Exemplo 3: Criando um administrador (começará como ativo)
    create_user(
        username='tiago', 
        password='123456', 
        name='Tiago Ribeiro', 
        email='tiago.admin@empresa.com',
        cpf='999.888.777-40',
        role='admin'
    )

    print("--- Processo finalizado ---")
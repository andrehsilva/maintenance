# -----------------------------------------------------------------------------
# README.md - Instruções do Projeto (Versão 2.1)
# -----------------------------------------------------------------------------
"""
# Sistema de Gestão de Manutenção com Flask (V2.1)

Esta versão inclui cadastro de clientes, diferenciação de usuários e um comando
dedicado para inicializar o banco de dados de forma segura.

## Estrutura do Projeto

/
|-- app.py             # Arquivo principal da aplicação Flask
|-- requirements.txt   # Dependências do Python
|-- templates/         # Pasta para os arquivos HTML
|-- static/

## Como Executar o Projeto

1.  **Instale as dependências:**
    ```bash
    pip install Flask Flask-SQLAlchemy Flask-Login Werkzeug click
    ```

2.  **Crie e Inicialize o Banco de Dados:**
    - No seu terminal, na pasta do projeto, execute o seguinte comando:
    ```bash
    flask init-db
    ```
    - Você verá mensagens confirmando que as tabelas foram criadas. Este comando
      deve ser executado apenas uma vez ou sempre que você precisar recriar o banco.

3.  **Execute a Aplicação:**
    ```bash
    flask run
    ```
    (Ou `flask run --port=5001` se a porta 5000 estiver ocupada)

4.  **Acesse e Cadastre o Admin:**
    - Acesse http://127.0.0.1:5000.
    - **O primeiro usuário que você cadastrar será automaticamente o Administrador.**
    - Todos os usuários subsequentes serão Técnicos.
"""
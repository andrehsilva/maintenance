# Etapa 1: Imagem Base
# Usamos uma imagem oficial do Python, leve e segura.
FROM python:3.11-slim

# Etapa 2: Diretório de Trabalho
# Define a pasta padrão dentro do container para a nossa aplicação.
WORKDIR /app

# Etapa 3: Instalação do 'uv'
# Usamos o pip da imagem base para instalar o 'uv', que é mais rápido.
RUN pip install uv

# Etapa 4: Instalação das Dependências
# Copiamos apenas o requirements.txt primeiro para otimizar o cache.
# Se este arquivo não mudar, o Docker não reinstala tudo de novo.
COPY requirements.txt .
# Linha correta
RUN uv pip install --system --no-cache-dir -r requirements.txt

# Etapa 5: Copiar o Código da Aplicação
# Copia todos os outros arquivos (app.py, etc.) para dentro do container.
COPY . .

# Etapa 6: Expor a Porta
# Informa ao Docker que a nossa aplicação vai rodar na porta 8000.
EXPOSE 8000

# Etapa 7: Comando de Inicialização
# Este é o comando que executa sua aplicação usando Gunicorn.
# --workers 4: Número de processos para lidar com requisições.
# --bind 0.0.0.0:8000: Permite que o Gunicorn seja acessado de fora do container.
# app:app: Significa "no arquivo app.py, use a variável chamada app".
CMD ["gunicorn", "--workers", "4", "--bind", "0.0.0.0:8000", "app:app"]
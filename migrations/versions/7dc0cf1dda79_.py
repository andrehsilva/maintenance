# /app/migrations/versions/7dc0cf1dda79_.py

"""empty message
Revision ID: 7dc0cf1dda79
Revises: b0f52d55ec40
Create Date: 2025-09-06 09:00:00.123456
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7dc0cf1dda79'
down_revision = 'b0f52d55ec40' # Certifique-se que este é o ID da sua migração anterior
branch_labels = None
depends_on = None


def upgrade():
    # ### Início dos comandos ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        # Etapa 1: Adicionar colunas como NULÁVEIS para não dar erro
        batch_op.add_column(sa.Column('name', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('email', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('cpf', sa.String(length=14), nullable=True))

    # Etapa 2: Preencher os dados dos usuários existentes com valores padrão
    # Usamos o username como base para garantir unicidade temporária
    op.execute("""
        UPDATE "user"
        SET name = username,
            email = username || '@email-temporario.com',
            cpf = username || '-0000'
        WHERE name IS NULL OR email IS NULL OR cpf IS NULL
    """)

    with op.batch_alter_table('user', schema=None) as batch_op:
        # Etapa 3: Agora que todos os campos estão preenchidos, alteramos para NOT NULL
        batch_op.alter_column('name', existing_type=sa.String(length=120), nullable=False)
        batch_op.alter_column('email', existing_type=sa.String(length=120), nullable=False)
        batch_op.alter_column('cpf', existing_type=sa.String(length=14), nullable=False)
        
        # Recriar as constraints de unicidade
        batch_op.create_unique_constraint(batch_op.f('uq_user_cpf'), ['cpf'])
        batch_op.create_unique_constraint(batch_op.f('uq_user_email'), ['email'])

    # ### Fim dos comandos ###


def downgrade():
    # ### Início dos comandos ###
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('uq_user_email'), type_='unique')
        batch_op.drop_constraint(batch_op.f('uq_user_cpf'), type_='unique')
        batch_op.drop_column('cpf')
        batch_op.drop_column('email')
        batch_op.drop_column('name')
    # ### Fim dos comandos ###
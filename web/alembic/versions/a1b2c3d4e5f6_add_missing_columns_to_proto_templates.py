"""add missing columns to proto_templates

Revision ID: a1b2c3d4e5f6
Revises: ceb3071c66c1
Create Date: 2026-08-17 13:00:00.000000

Добавляет колонки которые отсутствуют в initial миграции:
- proto_templates.title: увеличение длины с 32 до 64
- proto_templates.description
- proto_templates.metrics_parser_libs
- proto_templates.process_user_item_script
- proto_templates.process_user_libs
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'ceb3071c66c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Добавляет недостающие колонки в proto_templates.
    """
    # 1. Изменяем длину title с 32 на 64
    op.alter_column('proto_templates', 'title',
                    existing_type=sa.String(length=32),
                    type_=sa.String(length=64),
                    existing_nullable=False)
    
    # 2. Добавляем новые колонки
    op.add_column('proto_templates', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('proto_templates', sa.Column('metrics_parser_libs', sa.String(length=512), nullable=True))
    op.add_column('proto_templates', sa.Column('process_user_item_script', sa.Text(), nullable=True))
    op.add_column('proto_templates', sa.Column('process_user_libs', sa.String(length=512), nullable=True))
    
    print("✓ Добавлены недостающие колонки в proto_templates")


def downgrade() -> None:
    """
    Откат: удаляет добавленные колонки.
    """
    # Удаляем колонки в обратном порядке
    op.drop_column('proto_templates', 'process_user_libs')
    op.drop_column('proto_templates', 'process_user_item_script')
    op.drop_column('proto_templates', 'metrics_parser_libs')
    op.drop_column('proto_templates', 'description')
    
    # Возвращаем старую длину title
    op.alter_column('proto_templates', 'title',
                    existing_type=sa.String(length=64),
                    type_=sa.String(length=32),
                    existing_nullable=False)
    
    print("✓ Удалены добавленные колонки из proto_templates")

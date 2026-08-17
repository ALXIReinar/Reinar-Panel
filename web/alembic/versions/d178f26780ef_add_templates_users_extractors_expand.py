"""add templates_users_extractors EXPAND

Revision ID: d178f26780ef
Revises: ceb3071c66c1
Create Date: 2026-08-10 12:30:12.995460

EXPAND PHASE миграции:
- Мигрируем данные из proto_templates.flatten_json_users_key/flatten_user_identifier_key
  в templates_users_extractors.flatten_array_cursor/extractor_script
- Старые колонки в proto_templates НЕ удаляем (обе структуры работают параллельно)
- После периода мониторинга будет создана миграция CONTRACT PHASE для удаления старых колонок
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'd178f26780ef'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    EXPAND PHASE: Миграция данных из proto_templates в templates_users_extractors.
    
    Маппинг полей:
    - proto_templates.flatten_json_users_key → templates_users_extractors.flatten_array_cursor
    - proto_templates.flatten_user_identifier_key → templates_users_extractors.extractor_script
    
    Старые колонки в proto_templates СОХРАНЯЮТСЯ для совместимости.
    """
    conn = op.get_bind()
    
    # 1. Создаём новую таблицу templates_users_extractors
    print("✓ Создаём таблицу templates_users_extractors")
    op.create_table(
        'templates_users_extractors',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), autoincrement=True, nullable=False),
        sa.Column('tmp_id', sa.Integer(), nullable=False),
        sa.Column('flatten_array_cursor', sa.String(length=1024), nullable=False),
        sa.Column('extractor_script', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['tmp_id'], ['proto_templates.id'], name='templates_users_extractors_tmp_id_fkey', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='templates_users_extractors_pkey')
    )
    
    # 2. Миграция данных: копируем из proto_templates в templates_users_extractors
    print("✓ Копируем данные из proto_templates в templates_users_extractors")
    conn.execute(text("""
        INSERT INTO templates_users_extractors 
            (tmp_id, flatten_array_cursor, extractor_script)
        SELECT 
            pt.id as tmp_id,
            pt.flatten_json_users_key as flatten_array_cursor,
            pt.flatten_user_identifier_key as extractor_script
        FROM proto_templates pt
        WHERE pt.flatten_json_users_key IS NOT NULL 
           OR pt.flatten_user_identifier_key IS NOT NULL
    """))
    
    # 3. Получаем количество мигрированных записей для логирования
    result = conn.execute(text("SELECT COUNT(*) FROM templates_users_extractors"))
    count = result.scalar()
    print(f"✓ Мигрировано {count} записей в templates_users_extractors")


def downgrade() -> None:
    """
    Откат EXPAND PHASE: Удаляем таблицу templates_users_extractors.
    
    Данные в proto_templates остаются нетронутыми (они никогда не удалялись).
    """
    # Удаляем таблицу полностью
    op.drop_table('templates_users_extractors')
    
    print("✓ Таблица templates_users_extractors удалена (откат EXPAND PHASE)")

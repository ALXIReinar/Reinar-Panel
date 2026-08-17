"""sync shadow with dev structure - CONTRACT PHASE

Revision ID: e3f4a8b9c1d2
Revises: d178f26780ef
Create Date: 2026-08-17 12:00:00.000000

CONTRACT PHASE миграции (продолжение после d178f26780ef):
1. Создаёт таблицу templates_users_extractors (если не существует - для shadow DB)
2. Добавляет колонку libs в templates_users_extractors
3. Изменяет extractor_script на NOT NULL
4. Удаляет устаревшие колонки из proto_templates (точка невозврата!)

ВАЖНО: Эта миграция удаляет данные из старых колонок безвозвратно.
Убедитесь что данные мигрированы корректно перед применением!
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'e3f4a8b9c1d2'
down_revision: Union[str, Sequence[str], None] = 'd178f26780ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Синхронизация shadow DB с dev DB структурой.
    """
    conn = op.get_bind()
    
    # Проверяем существование таблицы templates_users_extractors
    result = conn.execute(text("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'templates_users_extractors'
        )
    """))
    table_exists = result.scalar()
    
    if not table_exists:
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
    else:
        print("✓ Таблица templates_users_extractors уже существует")
    
    # Проверяем существование колонки libs
    result = conn.execute(text("""
        SELECT EXISTS (
            SELECT FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'templates_users_extractors'
            AND column_name = 'libs'
        )
    """))
    libs_exists = result.scalar()
    
    if not libs_exists:
        print("✓ Добавляем колонку libs в templates_users_extractors")
        op.add_column('templates_users_extractors', sa.Column('libs', sa.String(length=512), nullable=True))
    else:
        print("✓ Колонка libs уже существует")
    
    # Изменяем extractor_script на NOT NULL (сначала заполняем NULL значения)
    print("✓ Обновляем NULL значения в extractor_script на пустую строку")
    conn.execute(text("""
        UPDATE templates_users_extractors 
        SET extractor_script = '' 
        WHERE extractor_script IS NULL
    """))
    
    print("✓ Изменяем extractor_script на NOT NULL")
    op.alter_column('templates_users_extractors', 'extractor_script',
                    existing_type=sa.Text(),
                    nullable=False)
    
    # Удаляем устаревшие колонки из proto_templates
    columns_to_drop = [
        'flatten_json_users_key',
        'flatten_user_identifier_key',
        'api_add_user_script',
        'api_delete_user_script',
        'add_script_custom_params',
        'delete_script_custom_params',
        'process_user_item_script',
        'process_user_libs'
    ]
    
    for column in columns_to_drop:
        # Проверяем существование колонки перед удалением
        result = conn.execute(text(f"""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'proto_templates'
                AND column_name = '{column}'
            )
        """))
        column_exists = result.scalar()
        
        if column_exists:
            print(f"✓ Удаляем колонку {column} из proto_templates")
            op.drop_column('proto_templates', column)
        else:
            print(f"✓ Колонка {column} уже удалена")
    
    print("✅ Миграция завершена успешно!")


def downgrade() -> None:
    """
    Откат миграции - возвращает колонки в proto_templates.
    ВАЖНО: Данные в удалённых колонках будут потеряны!
    """
    conn = op.get_bind()
    
    # Возвращаем колонки в proto_templates
    op.add_column('proto_templates', sa.Column('process_user_libs', sa.String(length=512), nullable=True))
    op.add_column('proto_templates', sa.Column('process_user_item_script', sa.Text(), nullable=True))
    op.add_column('proto_templates', sa.Column('delete_script_custom_params', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=True))
    op.add_column('proto_templates', sa.Column('add_script_custom_params', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=True))
    op.add_column('proto_templates', sa.Column('api_delete_user_script', sa.Text(), nullable=True))
    op.add_column('proto_templates', sa.Column('api_add_user_script', sa.Text(), nullable=True))
    op.add_column('proto_templates', sa.Column('flatten_user_identifier_key', sa.String(length=128), nullable=True))
    op.add_column('proto_templates', sa.Column('flatten_json_users_key', sa.String(length=1024), nullable=True))
    
    # Изменяем extractor_script обратно на nullable
    op.alter_column('templates_users_extractors', 'extractor_script',
                    existing_type=sa.Text(),
                    nullable=True)
    
    # Удаляем колонку libs
    op.drop_column('templates_users_extractors', 'libs')
    
    print("✓ Откат миграции выполнен")

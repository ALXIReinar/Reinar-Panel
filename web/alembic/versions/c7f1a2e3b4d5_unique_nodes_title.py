"""unique index on nodes.title

Revision ID: c7f1a2e3b4d5
Revises: b4e8a1c9d2f0
Create Date: 2026-10-21 09:00:00.000000

"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = 'c7f1a2e3b4d5'
down_revision: str | Sequence[str] | None = 'b4e8a1c9d2f0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Проверка длины, дубликатов и создание уникального индекса на nodes.title."""
    conn = op.get_bind()

    # 1. Проверяем длину: если > 64 символов, обрезаем
    conn.execute(text("UPDATE nodes SET title = SUBSTRING(title FROM 1 FOR 64) WHERE LENGTH(title) > 64"))

    # 2. Проверяем дубликаты
    duplicates = conn.execute(text("SELECT title, COUNT(*) FROM nodes GROUP BY title HAVING COUNT(*) > 1")).fetchall()

    if duplicates:
        dups_info = [f"'{row[0]}' ({row[1]} шт.)" for row in duplicates]
        raise ValueError(
            f"Невозможно создать уникальный индекс на nodes.title: обнаружены дубликаты: {', '.join(dups_info)}"
        )

    # 3. Создаем уникальный индекс, если его еще нет
    existing_index = conn.execute(
        text("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'nodes' AND indexname IN ('nodes_title_key', 'ix_nodes_title')
        """)
    ).scalar()

    if not existing_index:
        op.create_index('ix_nodes_title', 'nodes', ['title'], unique=True)


def downgrade() -> None:
    """Удаление уникального индекса nodes.title."""
    conn = op.get_bind()
    existing_index = conn.execute(
        text("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'nodes' AND indexname IN ('nodes_title_key', 'ix_nodes_title')
        """)
    ).scalar()

    if existing_index:
        op.drop_index(existing_index, table_name='nodes')

"""merge metrics_parser_libs into proto_python_lib

Revision ID: b4e8a1c9d2f0
Revises: 8c7b68981995
Create Date: 2026-10-21 08:58:00.000000

"""

import logging
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = 'b4e8a1c9d2f0'
down_revision: str | Sequence[str] | None = '8c7b68981995'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Объединение библиотек proto_python_lib и metrics_parser_libs без повторов."""
    conn = op.get_bind()

    # В части баз (например, dev) столбец уже удалён вручную — тогда объединять нечего
    has_column = conn.execute(
        text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'proto_templates' AND column_name = 'metrics_parser_libs'
        """)
    ).scalar()
    if not has_column:
        logging.warning("proto_templates.metrics_parser_libs отсутствует: объединение библиотек пропущено.")
        return

    rows = conn.execute(text("SELECT id, proto_python_lib, metrics_parser_libs FROM proto_templates")).fetchall()

    for row in rows:
        row_id, p_lib, m_lib = row[0], row[1], row[2]
        libs1 = set(pkg.strip() for pkg in (p_lib or '').split(',') if pkg.strip())
        libs2 = set(pkg.strip() for pkg in (m_lib or '').split(',') if pkg.strip())
        merged_set = libs1 | libs2
        merged = ','.join(sorted(merged_set)) if merged_set else None

        if merged != p_lib:
            conn.execute(
                text("UPDATE proto_templates SET proto_python_lib = :merged WHERE id = :id"),
                {"merged": merged, "id": row_id},
            )


def downgrade() -> None:
    """Откат объединения невозможен без потери исходного разделения библиотек."""
    logging.warning("Откат объединения библиотек proto_python_lib не восстанавливает исходное разделение.")

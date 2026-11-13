"""user_subs: счётчики израсходованного трафика NOT NULL

Revision ID: f2a9c4d7e1b3
Revises: 1b4796488e05
Create Date: 2026-11-13 18:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f2a9c4d7e1b3'
down_revision: str | Sequence[str] | None = '1b4796488e05'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COUNTERS = ('used_mb', 'traffic_used_day_mb')


def upgrade() -> None:
    """
    used_mb и traffic_used_day_mb — NOT NULL.

    Коллектор метрик прибавляет прирост (used_mb = used_mb + N), а NULL + N = NULL: у подписки с NULL трафик
    не копился и лимит не срабатывал. NULL попадал из API подписок, когда поле не передавали.

    Миграция идемпотентна: на базе, где NOT NULL уже выставлен вручную, UPDATE не находит строк, а SET NOT NULL
    ничего не меняет.
    """
    for column in COUNTERS:
        op.execute(f"UPDATE user_subs SET {column} = 0 WHERE {column} IS NULL")
        op.alter_column(
            'user_subs', column, existing_type=sa.BIGINT(), nullable=False, existing_server_default=sa.text('0')
        )


def downgrade() -> None:
    for column in COUNTERS:
        op.alter_column(
            'user_subs', column, existing_type=sa.BIGINT(), nullable=True, existing_server_default=sa.text('0')
        )

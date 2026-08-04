# ⚙️ Как делать миграции на `asyncpg + alembic`

Для фиксации изменений в БД выполнить следующие шаги

#### 1. Автогенерация sqlalchemy моделей

> sqlacodegen postgresql+psycopg2://postgres:YOUR_PG_ADMIN_PASSW@127.0.0.1:5432/reinar_db --outfile web/db/models.py

#### 2. Коммит в alembic

Из корня проекта

> alembic -c web/alembic.ini revision --autogenerate -m "CHANGE_MSG"; alembic -c web/alembic.ini upgrade head
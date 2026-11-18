# arq_worker (фоновые задачи): зависимости

Карточка сервиса для скилла `sql-queries`. Эндпоинтов здесь нет — скилл `fastapi-endpoint` не
применяется.

Код лежит внутри `web/`, но это отдельный сервис: импортируй из `web.arq_worker.*`, а не из
`web.data` или `web.utils` админки.

## Задачи

- Задача — `async def имя(ctx: dict, ...)` в `web/arq_worker/funcs/`.
- Регистрация: список `functions` или `cron_jobs` в `web/arq_worker/arq_config.py`. Без этого
  воркер задачу не знает: `enqueue_job('имя', ...)` из админки поставит задачу, а воркер
  отбросит её с ошибкой «function not found» — в админке этого не видно.

## Зависимости — декораторы

Объявлены в `web/arq_worker/depends_fabric.py`; передают зависимость именованным аргументом,
поэтому в сигнатуре у неё значение по умолчанию `None`:

| Декоратор | Аргумент | Что даёт |
|---|---|---|
| `@pg_sql_dep` | `db: PgSql` | фасад `web.arq_worker.data.postgres.PgSql`, соединение из `ctx['pg_pool']` |
| `@arq_dep` | `arq: ArqRedis` | постановка следующих задач (цепочки) |
| `@aiohttp_dep` | `aio_http: ClientSession` | запросы к нод-клиентам |

```python
@pg_sql_dep
@arq_dep
async def reset_day_user_traffic(ctx: dict, outbox_event_ids: list[dict] | None = None, db: PgSql = None, arq: ArqRedis = None):
    ...
```

Вспомогательные функции задачи получают `db` аргументом — не открывай второе соединение.

## Остальное

- `log_event`: `from web.arq_worker.utils.arq_logger_config import log_event` (без `request`).
  В начале сообщения — метка задачи, например `\033[35m[ARQ Traffic Reset]\033[0m`.
- SQL: `web/arq_worker/data/sql_queries/<сущность>_sql.py`, регистрация в
  `web/arq_worker/data/postgres.py`.
- Тесты: `web/arq_worker/tests`; запуск `./run.py arq_worker tests/<путь> -q`.

# web (админка): эндпоинты и зависимости

Карточка сервиса для скиллов `fastapi-endpoint` и `sql-queries`. Здесь только то, что
отличает `web` от других сервисов; общие правила — в скиллах.

## Роутеры и доступ

- Главный роутер: `web/api/__init__.py`, `main_router = APIRouter(prefix="/api/v1")`.
  Новый роутер подключай туда (`main_router.include_router(...)`); у `nodes` — свой
  агрегатор `web/api/nodes/__init__.py`.
- Сегменты `/private`, `/public`, `/server` — по модели из скилла. Проверяет их глобальная
  `AuthUXASGIMiddleware` (`web/api/middleware.py`), не зависимость:
  - `/api/v1/private/*` (и всё, что не попало ниже) — JWT в cookie; id админа — `request.state.admin_id`;
  - `/api/v1/public/*` — без авторизации;
  - `/api/v1/server/*` — без JWT, но только с `127.0.0.1` (скрипты админки:
    `web/scripts/create_admin.py` → `/api/v1/server/admins/sign_up`) и из `NODES_PRIVATE_NETWORK`
    (нод-клиенты). Роутеры вида `server_router = APIRouter(prefix='/server/...')`.
- Наружу `web/admin.caddy` отдаёт только `/api/v1/public/*` (свой rate-limit) и
  `/api/v1/private/*`; `/server` из интернета недоступен.
- Эндпоинт для админа (`prefix='/private/...'`) добавляет параметр `_: JWTCookieDep`: он
  проставляет обновлённый `access_token` в cookie ответа. Без него сессия админа не
  продлевается (так сделано в 41 из 47 эндпоинтов; без него — служебные и публичные).

## Зависимости

| Алиас | Импорт | Что даёт |
|---|---|---|
| `PgSqlDep` | `web.data.postgres` | фасад `PgSql` (соединение из пула на время запроса) |
| `RedisDep` | `web.data.redis_storage` | клиент Redis |
| `ArqDep` | `web.config_dir.config` | `ArqRedis` — постановка задач в `arq_worker` |
| `NodeExecAiohttpDep` | `web.config_dir.config` | `aiohttp.ClientSession` для запросов к нод-клиентам |
| `JWTCookieDep` | `web.schemas.cookie_settings_schema` | продление cookie `access_token` (см. выше) |

## Остальное

- `log_event`: `from web.utils.logger_config import log_event`.
- Схемы запросов/ответов: `web/schemas/*_schema.py`.
- Логика, общая для нескольких эндпоинтов модуля, — `handlers.py` рядом с роутером
  (`web/api/users/handlers.py`); зависимости (`db`, `arq`) передаются туда аргументами.
- SQL: классы в `web/data/sql_queries/<сущность>_sql.py`, регистрация в `PgSql` —
  `web/data/postgres.py`.
- `RecordDict`: **пока нет** (бэклог J1) — схемы ответа с записями БД не вводи, отдавай словарь.
- Тесты: `web/tests/unit`, `web/tests/integrate`; запуск `./run.py web tests/<путь> -q`.

# node_client (агент на физической ноде): эндпоинты и зависимости

Карточка сервиса для скилла `fastapi-endpoint`. Здесь только то, что отличает `node_client` от
других сервисов; общие правила — в скилле.

**Базы данных здесь нет** — скилл `sql-queries` не применяется. Состояние инстансов ядер и
конфиги живут в буфере `ConfigWriteBuffer` (write-behind кеш, пишет на диск сам).

## Роутеры и доступ

- Главный роутер: `node_client/api/__init__.py`, `main_router = APIRouter(prefix='/api/v1/server')`.
  Новый роутер подключай туда.
- Доступ — `OnlyAdminAccessMiddleware` (`node_client/api/middleware.py`): запросы принимаются только
  с IP админки (`127.0.0.1`, `10.0.0.1`, `env.admin_panel_private_ip`). Отдельной зависимости для
  авторизации не нужно.
- Нод-клиент сам обращается к админке на `/api/v1/server/*` — см. карточку `web/api/CLAUDE.md`.

## Зависимости

| Алиас | Импорт | Что даёт |
|---|---|---|
| `CoreBuffersDep` | `node_client.api.proto_core.write_behind_caching_file` | `ConfigWriteBuffer` — инстансы ядер, их конфиги и состояние |
| `AioHttpAdminDep` | `node_client.config` | `aiohttp.ClientSession` для запросов к админке |

## Остальное

- `log_event`: `from node_client.utils.logger_config import log_event`. `request.state.admin_id`
  здесь нет.
- Схемы: `node_client/schemas/`.
- Особая обработка под ядро — скрипты шаблонов в песочнице (`node_client/api/sandbox`), а не
  ветки `if` по имени ядра в эндпоинте.
- Тесты: `node_client/tests`; `./run.py node_client tests/<путь> -q` (по умолчанию `--mode mock`).

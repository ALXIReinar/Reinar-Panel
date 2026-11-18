# sub (сервис подписок): эндпоинты и зависимости

Карточка сервиса для скиллов `fastapi-endpoint` и `sql-queries`. Здесь только то, что
отличает `sub` от других сервисов; общие правила — в скиллах.

Код `sub` лежит внутри `web/`, но это отдельный сервис: импортируй только из `web.sub.*`, не из
`web.data`, `web.utils` или `web.config_dir` админки.

## Роутеры и доступ

Глобальной авторизации (middleware) нет — доступ задаёт сам роутер. Кроме `/public` из общей
модели, у `sub` два особых сегмента:

| Сегмент | Роутер | Кто вызывает | Доступ |
|---|---|---|---|
| `/api/v1/public` | `web/sub/api/sub_api.py` | клиенты VPN (ссылка подписки) | без авторизации; снаружи — через `/sub/*` в `sub.caddy` |
| `/api/v1/tg-bot` | `web/sub/api/tg_routing/` | **только Telegram-бот этого проекта** | IP бота: `APIRouter(dependencies=[Depends(tg_routing_is_tg_bot_access)])`; наружу не отдаётся |
| `/api/v1/<платёжка>` | `web/sub/api/robo_payment/` | пользователь (оплата) и сервера провайдера (вебхук) | см. `web/sub/api/robo_payment/CLAUDE.md` |

- `/tg-bot` — пример API для конкретного микросервиса: по адресу видно, кто им пользуется.
  Новый эндпоинт для бота — сюда; проверка IP уже стоит на уровне роутера, отдельная
  зависимость не нужна.
- Публичный роутер и роутеры платёжек подключаются в `web/sub/api/__init__.py` (`main_router`),
  роутер бота — `tg_router` в `web/sub/api/tg_routing/__init__.py`; оба подключены в `web/sub/main.py`.

## Зависимости

| Алиас | Импорт | Что даёт |
|---|---|---|
| `PgSqlDep` | `web.sub.data.postgres` | фасад `PgSql` сервиса `sub` |
| `RedisDep` | `web.sub.data.redis_storage` | клиент Redis |
| `ArqDep` | `web.sub.config_dir.config` | `ArqRedis` — задачи в `arq_worker` |
| `RoboAiohttpDep` | `web.sub.config_dir.config` | `aiohttp.ClientSession` для API RoboKassa |
| `TgRoutingAccessDep` | `web.sub.anything` | доступ только с IP бота (403 иначе) |

## Остальное

- `log_event`: `from web.sub.config_dir.logger_config import log_event`. `request.state.admin_id`
  здесь нет — в логах указывай `user_id`, `tg_id`, `b64_id` и т.п.
- Схемы: `web/sub/schemas/`.
- SQL: `web/sub/data/sql_queries/<сущность>_sql.py`, регистрация в `PgSql` — `web/sub/data/postgres.py`.
- Время в платёжном API хранится без часового пояса — известная проблема (бэклог D6); новый код
  не должен её усугублять, но и чинить попутно не надо.
- `RecordDict`: **пока нет** (бэклог J1).
- Тесты: `web/sub/tests`; запуск `./run.py sub tests/<путь> -q`.

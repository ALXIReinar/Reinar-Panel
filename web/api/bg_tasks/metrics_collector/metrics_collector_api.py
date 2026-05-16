import asyncio
from fastapi import APIRouter
from starlette.requests import Request

from web.api.bg_tasks.metrics_collector.handlers import run_traffic_sync_background
from web.data.postgres import PgSqlDep
from web.utils.logger_config import log_event

router = APIRouter()
background_tasks = set()


@router.put("/crons/traffic_sync")
async def collect_metrics_api(request: Request, db: PgSqlDep):
    """Обновляет трафик пользователей"""
    "Получаем список АКТИВНЫХ и ВИДИМЫХ для пользователя нод, с которых можно собрать метрики(есть metrics_port)"
    nodes = await db.nodes_protocols.get_all_nodes_for_metrics()
    log_event(f'Ноды для обновления трафика | nodes_len: \033[32m{len(nodes)}\033[0m')

    "Запускаем задачу в фон через asyncio, чтобы не забивать пул celery"
    # Мы передаем lifespan объекты сессий (async_session_maker), чтобы таска не исчезла при завершении жизни запроса
    task = asyncio.create_task(run_traffic_sync_background(nodes, request.app.state.cmd_center_aiohttp, request.app.state.pg_pool))
    log_event(f'Сбор метрик и обновление трафика в фоне | nodes_len: \033[32m{len(nodes)}\033[0m')

    # Чтобы Python не сожрал задачу сборщиком мусора сохраняем ссылку на таску в глобальный set
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard) # Сама себя удалит, когда завершится
    return {"success": True, "message": "Начались обсчёт метрик и обновление трафика пользователей"}

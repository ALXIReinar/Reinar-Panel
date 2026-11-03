"""
Инициализация нод-клиента при старте приложения

Запрашивает данные у админки через /startup эндпоинт,
компилирует скрипты и регистрирует все виртуальные ноды.
"""

import asyncio
from typing import TYPE_CHECKING

import aiohttp

from node_client.config import env
from node_client.utils.logger_config import log_event

if TYPE_CHECKING:
    from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer


async def fetch_startup_data(node_proto_ids: list[int] | None = None, retries: int | None = None) -> dict:
    """
    Запрашивает служебные данные виртуальных нод у админки

    Args:
        node_proto_ids: Список ID виртуальных нод (пустой = все зарегистрированные)
        retries: Число попыток. По умолчанию env.startup_retries (старт приложения);
            реинициализация передаёт 1 — вызывающий ждёт ответа и не должен висеть минутами

    Returns:
        dict: Ответ от /startup с ключами 'nodes', 'missing', 'node_title'

    Raises:
        RuntimeError: если не удалось подключиться после всех попыток
    """
    if node_proto_ids is None:
        node_proto_ids = []
    if retries is None:
        retries = env.startup_retries

    url = f"{env.effective_admin_panel_url}/api/v1/server/nodes/{env.node_title}/startup"
    payload = {"node_proto_ids": node_proto_ids}

    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 404:
                        body = await resp.json()
                        raise RuntimeError(f"Админка не знает ноду '{env.node_title}': {body.get('detail', body)}")

                    resp.raise_for_status()
                    data = await resp.json()

                    log_event(
                        f"Данные от /startup получены | nodes: \033[32m{len(data.get('nodes', []))}\033[0m; "
                        f"missing: \033[33m{data.get('missing', [])}\033[0m"
                    )
                    return data

        except aiohttp.ClientError as e:
            last_error = e
            log_event(
                f"Попытка {attempt}/{retries} подключения к админке | "
                f"url: \033[34m{url}\033[0m; error: \033[31m{repr(e)}\033[0m",
                level='WARNING',
            )
        except RuntimeError:
            raise
        except Exception as e:
            last_error = e
            log_event(
                f"Попытка {attempt}/{retries} | непредвиденная ошибка: \033[31m{repr(e)}\033[0m",
                level='WARNING',
            )

        if attempt < retries:
            await asyncio.sleep(env.startup_retry_delay_s)

    raise RuntimeError(
        f"Не удалось подключиться к админке (попыток: {retries}). URL: {url}. Последняя ошибка: {repr(last_error)}"
    )


async def phys_node_sys_init(buffer: 'ConfigWriteBuffer') -> None:
    """
    Инициализация физической ноды при старте приложения

    Запрашивает все зарегистрированные виртуальные ноды у админки
    и регистрирует их в ConfigWriteBuffer.

    Args:
        buffer: Экземпляр ConfigWriteBuffer

    Raises:
        RuntimeError: если не удалось подключиться к админке
        NodeInitError: если ошибка валидации/компиляции любой ноды
    """
    log_event(
        f"Инициализация физической ноды | node_title: \033[35m{env.node_title}\033[0m; "
        f"admin_url: \033[34m{env.effective_admin_panel_url}\033[0m"
    )

    data = await fetch_startup_data(node_proto_ids=[])

    nodes = data.get('nodes', [])
    missing = data.get('missing', [])

    registered_count = 0
    for item in nodes:
        await buffer.register_node(item)
        registered_count += 1

    log_event(
        f"Инициализация завершена | "
        f"зарегистрировано: \033[32m{registered_count}\033[0m; "
        f"missing: \033[33m{missing}\033[0m"
    )

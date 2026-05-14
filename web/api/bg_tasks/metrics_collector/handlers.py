import asyncio
import json
import math
import re
from collections import defaultdict

import jmespath
from aiohttp import ClientSession, ClientResponseError
from asyncpg import Pool, Record

from web.config_dir.config import env
from web.data.postgres import PgSql
from web.utils.anything import NodeUris
from web.utils.logger_config import log_event


def parse_node_output(script_text: str, stdout: str):
    """
    Выполняет динамический код парсера.
    В скрипте должна быть определена функция parse(data)
    """
    # Локальное окружение для скрипта
    local_scope = {}
    # Доступные либы в окружении исполняемого скрипта
    global_scope = {
        "json": json,
        "re": re,
        "math": math,
        "defaultdict": defaultdict,
        "jmespath": jmespath,
        # Запрещаем опасные встроенные функции типа open, eval, import
        "__builtins__": {
            "int": int, "str": str, "float": float, "list": list, "dict": dict,
            "set": set, "len": len, "range": range, "round": round, "print": print,
            "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
            "Exception": Exception, "ValueError": ValueError
        }
    }

    try:
        exec(script_text, global_scope, local_scope)
        # Вызываем функцию parse, которую юзер написал в шаблоне
        return local_scope['parse'](stdout)
    except Exception as e:
        log_event(f'Упал скрипт парсинга stdout метрик | parse_code: {script_text}; exception: {e}', level='ERROR')
        return f"Ошибка парсера: {e}"


async def run_traffic_sync_background(nodes: list, aio_http: ClientSession, pool: Pool):
    """Фоновая функция, которая будет крутиться отдельно от HTTP"""
    sem = asyncio.Semaphore(env.node_metrics_queue_limit)  # Имитируем исполнение батчами(по очереди по 8 нод)

    async def worker(node: Record):
        async with sem:
            try:
                "Запрашиваем метрики потребления с нод"
                url = f"http://{node['private_ip']}:{node['api_port']}{NodeUris.get_metrics}"
                async with aio_http.get(
                        url, params={'metrics_port': node['metrics_port'], 'command': node['metrics_command']}, timeout=10.0
                ) as resp:
                    resp.raise_for_status()
                    resp = await resp.json()

                "Парсим stdout скриптом пользователя"
                parsed_data, troubles = parse_node_output(node['metrics_parser_code'], resp['stdout'])
                if troubles:
                    log_event(f'Часть stdout не удалось обработать скриптом пользователя | troubles: {troubles}; node: \033[33m{repr(node)}\033[0m', level='WARNING')

                "Обновляем трафик, если был"
                if parsed_data:
                    async with pool.acquire() as conn:
                        db = PgSql(conn)
                        usernames, traffic_adds = zip(*tuple(
                            tuple(user_dict.items()) for user_dict in parsed_data
                        ))
                        await db.users.update_traffic(usernames, traffic_adds)

                log_event(f'Обновили трафик пользователей по метрикам | node: \033[36m{repr(node)}\033[0m')

            except ClientResponseError as e:
                log_event(f'Нода ответила, не удалось собрать метрики | status_code: \033[33m{e.status}\033[0m; response: \033[37m{e}\033[0m;node: \033[36m{repr(node)}\033[0m', level='ERROR')

            except Exception as e:
                log_event(f'Ошибка исполнения на админке, не удалось собрать метрики | error: \033[31m{e}\033[0m; node: \033[33m{repr(node)}\033[0m', level='CRITICAL')

    "Запускаем все воркеры"
    await asyncio.gather(*(worker(node) for node in nodes))
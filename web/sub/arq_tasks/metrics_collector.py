import asyncio
import importlib
import json
import math
import re
from collections import defaultdict

import flatten_json
import jmespath
from aiohttp import ClientResponseError, ClientSession
from arq import ArqRedis
from asyncpg import Pool

from web.arq_tasks.depends_fabric import aiohttp_dep, pg_sql_dep, arq_dep
from web.config_dir.config import env
from web.sub.data.postgres import PgSql
from web.sub.anything import NodeUris
from web.utils.arq_logger_config import log_event


@pg_sql_dep
@arq_dep
async def traffic_sync_scheduler(ctx: dict, db: PgSql = None, arq: ArqRedis = None):
    """
    Крона синхронизации трафика
    Запускается: каждые 5 минут
    Запускает Task Chaining: находит ноды для сбора трафика, отправляет их далее в Arq
    """
    log_event('\033[36m[ARQ]\033[0m Планировщик синхронизации трафика запущен')

    "Получаем список АКТИВНЫХ и ВИДИМЫХ для пользователя нод, с которых можно собрать метрики(есть metrics_port)"
    nodes = await db.users_subs.get_all_nodes_for_metrics()
    nodes = [dict(node) for node in nodes]

    if not nodes:
        log_event('\033[36m[ARQ]\033[0m Нет активных нод для сбора метрик', level='ERROR')
        return {'success': True, 'nodes_count': 0}

    "Ставим задачу сбора метрик в очередь. Task Chaining"
    job = await arq.enqueue_job('collect_traffic_metrics', nodes)
    log_event(
        f'\033[36m[ARQ]\033[0m Найдены ноды для сбора метрик. Задача поставлена в очередь | job_id: \033[33m{job.job_id}\033[0m; nodes_count: \033[32m{len(nodes)}\033[0m')
    return {'success': True, 'job_id': job.job_id, 'nodes_count': len(nodes)}




@aiohttp_dep
async def collect_traffic_metrics(ctx: dict, nodes: list[dict], aio_http: ClientSession = None):
    """
    Сбор метрик трафика с нод и обновление в БД
    
    Args:
        ctx: ARQ контекст (содержит pg_pool и aio_http из startup для декораторов)
        nodes: Список нод для сбора метрик
    """
    log_event(f'\033[35m[ARQ]\033[0m Начало сбора метрик трафика | nodes_count: \033[32m{len(nodes)}\033[0m')
    
    sem = asyncio.Semaphore(env.node_metrics_queue_limit)  # Батчинг по 8 нод
    success_count = 0
    error_count = 0
    

    async def worker(node: dict, pool: Pool):
        nonlocal success_count, error_count
        
        async with sem:
            try:
                "Запрашиваем метрики потребления с нод"
                url = f"http://{node['private_ip']}:{node['api_port']}{NodeUris.get_metrics}"
                # url = f"http://localhost:8200{NodeUris.get_metrics}"
                json_body = {
                    'metrics_port': node['metrics_port'],
                    'command': node['metrics_command'],
                    'metrics_script': node['api_metrics_script'],
                    'core_lib': node['proto_python_lib'],
                    'custom_params': node['metrics_script_custom_params'],
                }
                async with aio_http.post(url, json=json_body, timeout=10.0) as resp:
                    resp.raise_for_status()
                    resp_data = await resp.json()
                
                "Парсим stdout скриптом пользователя"
                parsed_data, troubles = await parse_node_output(node['metrics_parser_code'], resp_data['stdout'], node['sub_required_libs'])
                if parsed_data is None:
                    log_event(f'\033[35m[ARQ]\033[0m Часть stdout не удалось обработать | troubles: {troubles}; node_proto_id: \033[33m{node["id"]}\033[0m', level='WARNING')

                "Обновляем трафик, если был"
                if parsed_data:
                    usernames, traffic_adds = zip(*tuple(
                        tuple(user_dict.items()) for user_dict in parsed_data
                    ))
                    async with pool.acquire() as conn:
                        await PgSql(conn).sub.update_traffic(usernames, traffic_adds)
                    
                    success_count += 1
                    log_event(f'\033[35m[ARQ]\033[0m Метрики обновлены | node_proto_id: \033[36m{node["id"]}\033[0m; users_count: \033[32m{len(parsed_data)}\033[0m')
                else:
                    log_event(f'\033[35m[ARQ]\033[0m Нет данных для обновления | node_proto_id: \033[33m{node["id"]}\033[0m', level='WARNING')
            
            except ClientResponseError as e:
                error_count += 1
                log_event(f'\033[35m[ARQ]\033[0m Нода ответила с ошибкой, не удалось собрать метрики | status_code: \033[33m{e.status}\033[0m; response: \033[37m{e}\033[0m;node: \033[36m{repr(node)}\033[0m', level='ERROR')
            
            except Exception as e:
                error_count += 1
                log_event(f'\033[35m[ARQ]\033[0m Ошибка исполнения на админке, не удалось собрать метрики | error: \033[31m{e}\033[0m; node: \033[33m{repr(node)}\033[0m', level='CRITICAL')
    
    "Запускаем все воркеры"
    await asyncio.gather(*(worker(node, ctx['pg_pool']) for node in nodes))
    log_event(f'\033[35m[ARQ]\033[0m Сбор метрик завершён | success: \033[32m{success_count}\033[0m; errors: \033[31m{error_count}\033[0m')
    return {'success': True, 'nodes_total': len(nodes), 'success_count': success_count, 'error_count': error_count}



async def parse_node_output(script_text: str, stdout: str, lib_names: str):
    """
    Выполняет динамический код парсера.
    В скрипте должна быть определена функция parse(data)
    """
    try:
        # Подгружаем библиотеки пользователя
        user_libs = {lib_name: importlib.import_module(lib_name) for lib_name in lib_names}
        # Локальное окружение для скрипта
        local_scope = {}
        # Доступные либы в окружении исполняемого скрипта
        global_scope = {
            **user_libs,
            "json": json,
            "re": re,
            "math": math,
            "defaultdict": defaultdict,
            "jmespath": jmespath,
            "flatten_json": flatten_json,
            # Запрещаем опасные встроенные функции типа open, eval, import
            "__builtins__": {
                "int": int, "str": str, "float": float, "list": list, "dict": dict,
                "set": set, "len": len, "range": range, "round": round, "print": print,
                "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
                "Exception": Exception, "ValueError": ValueError
            }
        }
        # Выполняем скрипт
        exec(script_text, global_scope, local_scope)

        "Вызываем функцию из скрипта"
        parse_func = local_scope.get("parse")
        if not parse_func:
            return False, "функция parse не найдена в скрипте!"

        result = parse_func(script_text, stdout, lib_names)

        "Если async"
        if asyncio.iscoroutine(result):
            result = await result

        log_event(f"Успешно Обработали stdout сбора метрик")
        return result

    except ImportError as e:
        error_msg = f"Библиотека {lib_names} не найдена | original_exception: {e}"
        log_event(error_msg, level='CRITICAL')
        return None, error_msg

    except Exception as e:
        error_msg = f"Ошибка выполнения action_script скрипта | exception: {e}"
        log_event(error_msg, level='CRITICAL')
        return None, error_msg
import asyncio
import importlib
import json
import math
import re
import traceback
from collections import defaultdict

import flatten_json
import jmespath
import orjson
from aiohttp import ClientResponseError, ClientSession
from arq import ArqRedis
from asyncpg import Pool

from web.sub.arq_tasks.depends_fabric import aiohttp_dep, pg_sql_dep, arq_dep
from web.sub.config_dir.config import env
from web.sub.data.postgres import PgSql
from web.sub.anything import NodeUris
from web.sub.config_dir.arq_logger_config import log_event


@pg_sql_dep
@arq_dep
async def traffic_sync_scheduler(ctx: dict, db: PgSql = None, arq: ArqRedis = None):
    """
    Крона синхронизации трафика
    Запускается: каждые 5 минут
    Запускает Task Chaining: находит ноды для сбора трафика, отправляет их далее в Arq
    """
    log_event('\033[36m[ARQ Metrics Collector]\033[0m Планировщик синхронизации трафика запущен')

    "Получаем список АКТИВНЫХ и ВИДИМЫХ для пользователя нод, с которых можно собрать метрики(есть metrics_port)"
    nodes = await db.users_subs.get_all_nodes_for_metrics()
    nodes = [dict(node) for node in nodes]

    if not nodes:
        log_event('\033[36m[ARQ Metrics Collector]\033[0m Нет активных нод для сбора метрик', level='ERROR')
        return {'success': True, 'nodes_count': 0}

    "Ставим задачу сбора метрик в очередь. Task Chaining"
    job = await arq.enqueue_job('collect_traffic_metrics', nodes)
    log_event(
        f'\033[36m[ARQ Metrics Collector]\033[0m Найдены ноды для сбора метрик. Task Chaining, depth: \033[35m0\033[0m. Задача поставлена в очередь | job_id: \033[33m{job.job_id}\033[0m; nodes_count: \033[32m{len(nodes)}\033[0m')
    return {'success': True, 'job_id': job.job_id, 'nodes_count': len(nodes)}




@aiohttp_dep
@arq_dep
async def collect_traffic_metrics(ctx: dict, nodes: list[dict], aio_http: ClientSession = None, arq: ArqRedis = None):
    """
    Сбор метрик трафика с нод и обновление в БД
    
    Args:
        ctx: ARQ контекст (содержит pg_pool и aio_http из startup для декораторов)
        nodes: Список нод для сбора метрик
    """
    log_event(f'\033[36m[ARQ Metrics Collector]\033[0m Начало сбора метрик трафика | nodes_count: \033[32m{len(nodes)}\033[0m')
    
    sem = asyncio.Semaphore(env.action_on_core_proto_limit)  # Батчинг по 8 нод
    success_count = 0
    error_count = 0
    

    async def worker(node: dict, pool: Pool):
        nonlocal success_count, error_count
        
        async with sem:
            try:
                "Запрашиваем метрики потребления с нод"
                url = f"http://{node['private_ip']}:{node['api_port']}{NodeUris.get_metrics}"
                # url = f"http://localhost:8000{NodeUris.get_metrics}"
                json_body = {
                    'metrics_port': node['metrics_port'],
                    'command': node['metrics_command'],
                    'metrics_script': node['api_metrics_script'],
                    'core_lib': node['proto_python_lib'],
                }
                async with aio_http.post(url, json=json_body, timeout=10.0) as resp:
                    resp.raise_for_status()
                    resp_data = await resp.json()
                
                "Парсим stdout скриптом пользователя"
                script_res, script_res_pack, err_msg = await parse_node_output(node['metrics_parser_code'], resp_data['stdout'], node['sub_required_libs'])

                "Ошибка в скрипте. Ранняя остановка"
                if not script_res:
                    log_event(f'\033[31m[ARQ Metrics Collector]\033[0m Скрипт упал с ошибкой. stdout не удалось обработать | err: {err_msg}; node_proto_id: \033[33m{node["id"]}\033[0m', level='WARNING')
                    return

                "Трафик пользователей, Проблемные пользователи"
                parsed_data, troubles = script_res_pack
                if troubles:
                    log_event(f'\033[36m[ARQ Metrics Collector]\033[0m Часть stdout не удалось обработать | troubles: {troubles}; node_proto_id: \033[33m{node["id"]}\033[0m', level='WARNING')


                "Обновляем трафик, если был"
                if parsed_data:
                    usernames, traffic_adds = zip(*tuple(
                        tuple(user_dict.values()) for user_dict in parsed_data
                    ))
                    async with pool.acquire() as conn:
                        log_event(f'\033[35m[ARQ Metrics Collector Metrics Collector]\033[0m Outbox операций по удалению пользователей с ядра | node_proto_id: \033[36m{node["id"]}\033[0m;')
                        outbox_event_ids = await PgSql(conn).sub.update_traffic(usernames, traffic_adds)

                    if outbox_event_ids:
                        outbox_event_ids = [oe_id['id'] for oe_id in outbox_event_ids]
                        job = await arq.enqueue_job(
                            'bulk_delete_by_traffic_limit',
                            outbox_event_ids,
                        )
                        log_event(f'\033[36m[ARQ Metrics Collector]\033[0m \033[34mTask Chaining, depth: \033[31m1\033[0m Запустили бульк-удаление для пользователей, превысивших лимит трафика | events_len: {len(outbox_event_ids)}', job_id=job.job_id)

                    success_count += 1
                    log_event(f'\033[36m[ARQ Metrics Collector]\033[0m Метрики обновлены | node_proto_id: \033[36m{node["id"]}\033[0m; users_count: \033[32m{len(parsed_data)}\033[0m')
                else:
                    log_event(f'\033[36m[ARQ Metrics Collector]\033[0m Нет данных для обновления | node_proto_id: \033[33m{node["id"]}\033[0m', level='WARNING')
            
            except ClientResponseError as e:
                error_count += 1
                log_event(f'\033[36m[ARQ Metrics Collector]\033[0m Нода ответила с ошибкой, не удалось собрать метрики | status_code: \033[33m{e.status}\033[0m; response: \033[37m{e}\033[0m;node: \033[36m{repr(node)}\033[0m', level='ERROR')
            
            except Exception as e:
                error_count += 1
                log_event(f'\033[36m[ARQ Metrics Collector]\033[0m Ошибка исполнения на админке, не удалось собрать метрики | error: \033[31m{e}\033[0m; node: \033[33m{repr(node)}\033[0m', level='CRITICAL')
    
    "Запускаем все воркеры"
    await asyncio.gather(*(worker(node, ctx['pg_pool']) for node in nodes))
    log_event(f'\033[36m[ARQ Metrics Collector]\033[0m Сбор метрик завершён | success: \033[32m{success_count}\033[0m; errors: \033[31m{error_count}\033[0m')
    return {'success': True, 'nodes_total': len(nodes), 'success_count': success_count, 'error_count': error_count}


@arq_dep
@pg_sql_dep
async def bulk_delete_by_traffic_limit(ctx: dict, outbox_event_ids: list, arq: ArqRedis = None, db: PgSql = None):
    log_event(f'\033[31m[ARQ Metrics Collector]\033[0m \033[34mTask Chaining, depth: \033[33m2\033[0m Собираем данные и группируем пользователей по нодаи для отправки delete бульк-запроса | outbox_events_fst10: \033[37m{outbox_event_ids[:10]}\033[0m', level='WARNING')

    nodes_by_limited_users = await db.sub.get_vnodes_by_outbox_events(outbox_event_ids)
    users_to_delete = sum(len(vnode['users']) for vnode in nodes_by_limited_users)

    log_event(f'\033[31m[ARQ Metrics Collector]\033[0m Фон по удалению пользователей из ядер протоколов | total_deletes: \033[31m{users_to_delete}\033[0m')

    sem = asyncio.Semaphore(env.action_on_core_proto_limit)

    async def enqueue_delete(vnode):
        async with sem:
            log_event(f'\033[31m[ARQ Metrics Collector]\033[0m Отправляем Бульк запрос на фоновое удаление пользователей из ядра | node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m')
            job = await arq.enqueue_job(
                'bulk_delete_users_from_single_node',
                vnode['node_proto_id'],
                vnode['private_ip'],
                vnode['api_port'],
                vnode['metrics_port'],
                vnode['proto_python_lib'],
                vnode['api_bulk_delete_user_script'],
                vnode['bulk_delete_script_custom_params'],
                vnode['users'],
                vnode['reload_core_command'],
                vnode['config_path'],
                vnode['flatten_json_users_key'],
                vnode['flatten_user_identifier_key'],
            )
            log_event(f'\033[31m[ARQ Metrics Collector]\033[0m \033[34mTask Chaining, depth: \033[32m3\033[0m бульк delete летит на ноду | node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m')
            log_event(f'\033[31m[ARQ Metrics Collector]\033[0m Фоновая задача запущена | node_proto_id: \033[33m{vnode['node_proto_id']}\033[0m', job_id=job.job_id)

    "Размеренная параллельная обработка с ограничением через семафор"
    await asyncio.gather(*[enqueue_delete(vnode) for vnode in nodes_by_limited_users if len(vnode['users']) > 0])

    return {'success': True, 'message': 'Запущено Бульк удаление с нод', 'total_nodes': len(nodes_by_limited_users)}


async def parse_node_output(script_text: str, stdout: str, lib_names: str | None) -> tuple[bool, tuple, str]:
    """
    Выполняет динамический код парсера.
    В скрипте должна быть определена функция parse(data)

    WARNING. Возможна миграция обработки сырых метрик на нод-клиент
    Current: нод-клиент отдаёт сырой выход из get_metrics скрипта. Он обрабатывается на саб-сервисе/МС фона

    :returns
        Happy case: True, (user_statistics, troubles), 'Plug Message'
        Other Exception cases: False, (None, None), 'Err Reason'
    """
    "Обработка строки-списка библиотек"
    if lib_names is None:
        lib_names = []
    else:
        lib_names = lib_names.split(',')
    try:
        # Подгружаем библиотеки пользователя
        user_libs = {lib_name.strip(): importlib.import_module(lib_name.strip()) for lib_name in lib_names}
        # Локальное окружение для скрипта
        local_scope = {}
        # Доступные либы в окружении исполняемого скрипта
        global_scope = {
            **user_libs,
            "json": json,
            "asyncio": asyncio,
            "orjson": orjson,
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
                "isinstance": isinstance, "type": type, "dir": dir, "all": all, "any": any,
                "Exception": Exception, "ValueError": ValueError, "KeyError": KeyError,
                "NameError": NameError, "TypeError": TypeError, "AttributeError": AttributeError
            }
        }
        # Выполняем скрипт
        exec(script_text, global_scope, local_scope)

        "Вызываем функцию из скрипта"
        parse_func = local_scope.get("parse")
        if not parse_func:
            return False, (None, None), "функция parse не найдена в скрипте!"

        result = parse_func(stdout)

        "Если async"
        if asyncio.iscoroutine(result):
            result = await result

        log_event(f"Успешно Обработали stdout сбора метрик")
        return True, result, 'Успешно Обработали stdout сбора метрик'

    except ImportError as e:
        log_event(f"\033[31mОШИБКА ИМПОРТА БИБЛИОТЕКИ\033[0m\nБиблиотека: {lib_names}\nAction: Parse Metrics\nДетали: {str(repr(e))}",level='CRITICAL')
        return False, (None, None), f"Библиотека {lib_names} не найдена. Убедитесь что она установлена в виртуальном окружении."

    except SyntaxError as e:
        script_lines = script_text.split('\n')
        error_line = script_lines[e.lineno - 1] if e.lineno and e.lineno <= len(script_lines) else "???"

        log_event(f"\033[31mСИНТАКСИЧЕСКАЯ ОШИБКА В СКРИПТЕ\033[0m\nAction: Parse Metrics\nСтрока {e.lineno}: {error_line}\nОшибка: {e.msg}\nПозиция: {' ' * (e.offset - 1) if e.offset else ''}^\n", level='CRITICAL')

        return False, (None, None), f"Синтаксическая ошибка в скрипте: {e.msg} (строка {e.lineno})"

    except Exception as e:
        tb_str = traceback.format_exc()
        log_event(f"\033[31mОШИБКА ВЫПОЛНЕНИЯ СКРИПТА\033[0m\nAction: Parse Metrics\nБиблиотеки: {lib_names}\nТип ошибки: {type(e).__name__}\nСообщение: {str(e)}\n\nTraceback:\n{tb_str}\n", level='CRITICAL')
        return False, (None, None), f"Ошибка выполнения скрипта ({type(e).__name__}): {str(e)}"

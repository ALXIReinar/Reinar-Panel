import asyncio
from aiohttp import ClientResponseError, ClientSession
from asyncpg import Record, Pool

from web.arq_tasks.depends_fabric import pg_sql_dep, aiohttp_dep
from web.arq_tasks.metrics_collector.handlers import parse_node_output
from web.config_dir.config import env
from web.data.postgres import PgSql
from web.utils.anything import NodeUris
from web.utils.arq_logger_config import log_event


@aiohttp_dep
async def collect_traffic_metrics(ctx: dict, nodes: list[Record], aio_http: ClientSession = None):
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
    

    async def worker(node: Record, pool: Pool):
        nonlocal success_count, error_count
        
        async with sem:
            try:
                "Запрашиваем метрики потребления с нод"
                # url = f"http://{node['private_ip']}:{node['api_port']}{NodeUris.get_metrics}"
                url = f"http://localhost:8200{NodeUris.get_metrics}"
                async with aio_http.get(
                    url, params={'metrics_port': node['metrics_port'], 'command': node['metrics_command']}, timeout=10.0
                ) as resp:
                    resp.raise_for_status()
                    resp_data = await resp.json()
                
                "Парсим stdout скриптом пользователя"
                parsed_data, troubles = parse_node_output(node['metrics_parser_code'], resp_data['stdout'])
                
                if parsed_data is None:
                    log_event(f'\033[35m[ARQ]\033[0m Часть stdout не удалось обработать | troubles: {troubles}; node_id: \033[33m{node["id"]}\033[0m', level='WARNING')
                
                "Обновляем трафик, если был"
                if parsed_data:
                    usernames, traffic_adds = zip(*tuple(
                        tuple(user_dict.items()) for user_dict in parsed_data
                    ))
                    async with pool.acquire() as conn:
                        await PgSql(conn).users.update_traffic(usernames, traffic_adds)
                    
                    success_count += 1
                    log_event(f'\033[35m[ARQ]\033[0m Метрики обновлены | node_id: \033[36m{node["id"]}\033[0m; users_count: \033[32m{len(parsed_data)}\033[0m')
                else:
                    log_event(f'\033[35m[ARQ]\033[0m Нет данных для обновления | node_id: \033[33m{node["id"]}\033[0m', level='WARNING')
            
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

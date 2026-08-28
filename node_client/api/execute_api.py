import copy
import subprocess
from fastapi import APIRouter, HTTPException, Request

from node_client.api.proto_core.write_behind_caching_file import CoreBuffersDep
from node_client.api.sandbox.hot_reload_executor import HotReloadExecutor
from node_client.config import env
from node_client.utils.logger_config import log_event
from node_client.schemas.execute_schema import ExecuteResponseSchema, ExecuteCommandSchema, MetricsSchema

router = APIRouter(prefix='/node', tags=['Execute'])



@router.post('/execute', summary="Выполнить команду на ноде")
def execute_command(body: ExecuteCommandSchema):
    """
    Выполняет команду на ноде через subprocess.
    
    Timeout: 30 секунд по умолчанию
    """
    try:
        result = subprocess.run(
            body.command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=env.command_timeout
        )
        
        return ExecuteResponseSchema(
            success=result.returncode == 0,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
            command=body.command
        )
    
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail={"success": False, "message": f"Команда превысила timeout ({env.command_timeout}s)", "command": body.command})
    
    except Exception as e:
        raise HTTPException(status_code=500, detail={"success": False, "message": f"Ошибка выполнения команды: {str(e)}", "command": body.command})



@router.post('/metrics')
async def get_metrics(body: MetricsSchema, buffer: CoreBuffersDep, request: Request):
    """
    1. Скрипт сбора метрик с впн-ядра. Поддерживает 2 способа
    - cli команда
    - питон скрипт(Например, для обращения к апи ядра)

    Если настроены оба способа, предпочтение отдаётся апи скрипту
    - То есть СКРИПТ ОБРАБОТКИ МЕТРИК должен полагаться на ответ питон-скрипта
    * Для простоты мы рекомендуем учитывать в скрипте обработки метрик ОБА варианта


    2. Скрипт обработки метрик. Получает на вход
    - 1. Результат питон-скрипта/cli команды(из обоих предпочтение отдаётся питон-скрипту)
    - 2. Объект с пользователями впн-ядра. Представляет из себя словарь:
        {
            user_uuid_1: {**constant_node_data_obj, **constant_user_data_obj, **required_user_data_obj},
            user_uuid_2: {**constant_node_data_obj, **constant_user_data_obj, **required_user_data_obj},
            user_uuid_3: {**constant_node_data_obj, **constant_user_data_obj, **required_user_data_obj},
        }

    Его задача - отдать следующую струткуру
    [
        {user_sub_id: 1, total_adds_md: 1024},
        {user_sub_id: 2, total_adds_md: 2048},
        {user_sub_id: 3, total_adds_md: 3072},
    ]
    - user_sub_id - ID подписки(user_subs.id)
    - total_adds_md - прибавка к общему использованному трафику в МегаБайтах
    """

    # xray api statsquery --server=127.0.0.1:{} -pattern "user>>>" -reset
    cmd_str = body.command.format(body.metrics_port)
    # xray api statsquery --server=127.0.0.1:10085 -pattern "user>>>" -reset
    
    # Проверяем что нода зарегистрирована
    if body.node_proto_id not in buffer.buffer_storage:
        log_event(f'\033[35m[Metrics Grabbing]\033[0m Нода не зарегистрирована в буфере | node_proto_id: \033[31m{body.node_proto_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(
            status_code=404, 
            detail={
                "success": False, 
                "error": "Node not registered", 
                "message": f"Нода {body.node_proto_id} не зарегистрирована в ConfigWriteBuffer. Нет активных пользователей."
            }
        )
    
    try:

        api_metrics, cli_metrics = None, None
        "1.1. Пробуем получить метрики по Апи ядра"
        if body.metrics_script and body.metrics_port:
            log_event(f'\033[35m[Metrics Grabbing]\033[0m Сбор метрик Питон-скриптом | node_proto_id: \033[33m{body.node_proto_id}\033[0m; script: \033[34m{body.metrics_script[:200]}\033[0m', request=request)
            action_res, api_metrics = await HotReloadExecutor.execute_action_script(
                script=body.metrics_script,
                lib_names=body.core_lib,
                node_ip='127.0.0.1',
                core_api_port=body.metrics_port,
                action='get_metrics',
            )
        else:

            log_event(f'\033[35m[Metrics Grabbing]\033[0m] Сбор метрик CLI-командой | node_proto_id: \033[33m{body.node_proto_id}\033[0m; command: \033[34m{cmd_str}\033[0m', request=request)
            "1.2. Получение метрик по команде в cli, если не удалось по скрипту/нет скрипта"
            result = subprocess.run(
                cmd_str.split(), # ["xray", "api", "statsquery", "--server=127.0.0.1:10085", "-pattern", '"user>>>"', "-reset"]
                capture_output=True,
                text=True,
                timeout=env.command_timeout
            )
            if result.returncode == 0:
                cli_metrics = result.stdout

        "1.3. Выбираем результат"
        raw_metrics = api_metrics or cli_metrics
        if not raw_metrics:
            approach = "python-script" if body.metrics_script else "cli-command"
            log_event(f'\033[35m[Metrics Grabbing]\033[0m Не удалось собрать метрики | node_proto_id: \033[33m{body.node_proto_id}\033[0m; approach: \033[32m{approach}\033[0m', request=request, level='ERROR')
            raise HTTPException(status_code=400, detail={"success": False, "error": "Failed to get stats"})

        "2. Парсим ответ впн-ядра до формата"# [{user_sub_id: 1, total_adds_md: 1024}, ...]
        log_event(f'\033[35m[Metrics Grabbing]\033[0m Парсим метрики | node_proto_id: \033[33m{body.node_proto_id}\033[0m', request=request)
        success, traffic_pack = await HotReloadExecutor.execute_action_script(
            script=body.metrics_parser_code,
            lib_names=body.metrics_parser_libs,
            node_ip='0',                # Затычки для обязательных аргументов
            core_api_port=0,            # Затычки для обязательных аргументов
            action='parse_metrics',
            custom_params={
                "raw_metrics": raw_metrics,
                "vpn_users": copy.deepcopy(buffer.buffer_storage[body.node_proto_id]), # Отдаём копию, Read only!
                "local_state": buffer.local_state[body.node_proto_id], # А local_state может использовать как хочет
            }
        )

        if not success:
            log_event(f'\033[35m[Metrics Grabbing]\033[0m Не удалось обработать метрики | node_proto_id: \033[33m{body.node_proto_id}\033[0m; script: \033[34m{body.metrics_parser_code[:200]}\033[0m', request=request, level='ERROR')
            raise HTTPException(status_code=400, detail={"success": False, "error": "Failed to parse stats"})

        traffic_consuming, troubles = traffic_pack
        if troubles:
            log_event(f'\033[35m[Metrics Grabbing]\033[0m Часть stdout не удалось обработать | troubles: {troubles}; node_proto_id: \033[33m{body.node_proto_id}\033[0m', level='WARNING')

        return {"success": True, "users_traffic": traffic_consuming}

    except subprocess.TimeoutExpired:
        log_event(f'\033[35m[Metrics Grabbing]\033[0m CLI зависла/долго исполняется | node_proto_id: \033[33m{body.node_proto_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=408, detail={"success": False, "message": f"Команда превысила timeout ({env.command_timeout}s)", "command": cmd_str})

    except HTTPException:
        # Re-raise HTTPException. Иначе все исключения будут перехватываться как 500 в "Exception as e"
        raise

    except Exception as e:
        log_event('\033[35m[Metrics Grabbing]\033[0m Ошибка в эндпоинте нод клиента', request=request, level='CRITICAL')
        raise HTTPException(status_code=500, detail={"success": False, "message": f"Ошибка выполнения команды: {repr(e)}", "command": cmd_str})
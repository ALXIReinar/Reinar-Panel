import asyncio  # noqa: I001
import copy
import shlex
import subprocess
from typing import Any
from fastapi import APIRouter, HTTPException, Request, Response

from node_client.api.proto_core.write_behind_caching_file import CoreBuffersDep
from node_client.config import env
from node_client.schemas.execute_schema import (
    ExecuteCommandSchema,
    ExecuteResponseSchema,
    MetricsSchema,
)
from node_client.utils.logger_config import log_event

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
            # Эндпоинт намеренно выполняет shell-команды: админка шлёт только команды из whitelist_commands,
            # доступ к нод-клиенту — только из приватной сети (OnlyAdminAccessMiddleware)
            shell=True,  # nosemgrep
            capture_output=True,
            text=True,
            timeout=env.command_timeout,
        )
        return ExecuteResponseSchema(
            success=result.returncode == 0,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
            command=body.command,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=408,
            detail={
                "success": False,
                "message": f"Команда превысила timeout ({env.command_timeout}s)",
                "command": body.command,
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "message": f"Ошибка выполнения команды: {str(e)}", "command": body.command},
        )


@router.post('/metrics')
async def get_metrics(
    body: MetricsSchema,
    buffer: CoreBuffersDep,
    request: Request,
    response: Response,
):
    """
    Сбор и парсинг метрик с впн-ядра виртуальной ноды.
    Все служебные данные (скрипты, команды) берутся из метаданных ноды.
    """
    meta = buffer.get_metadata(body.node_proto_id)

    source: str | None = None
    raw: Any = None
    first_error: str | None = None

    # 1. Попытка получить метрики через API-скрипт ядра
    api_script = meta.get('api_metrics_script')
    if api_script:
        try:
            log_event(
                f"\033[35m[Metrics]\033[0m Сбор метрик API-скриптом | node_proto_id: \033[33m{body.node_proto_id}\033[0m",
                request=request,
            )
            res = api_script('127.0.0.1', body.metrics_port, {})
            if asyncio.iscoroutine(res):
                res = await res
            raw = res
            source = "api"
        except Exception as e:
            first_error = str(e)
            log_event(
                f"\033[35m[Metrics]\033[0m Ошибка API-скрипта сбора метрик: {e}",
                request=request,
                level='WARNING',
            )

    # 2. CLI-fallback строго при raw is None
    metrics_command = meta.get('metrics_command')
    if raw is None and metrics_command:
        try:
            # Внутри try: кривой шаблон команды ({port} вместо {}) — это 502 с причиной, а не голый 500
            cmd_str = metrics_command.format(body.metrics_port)
            log_event(
                f"\033[35m[Metrics]\033[0m Сбор метрик CLI-командой: {cmd_str}",
                request=request,
            )
            # В отдельном потоке: синхронный subprocess.run блокировал бы event loop всего нод-клиента
            # (воркеры буфера, другие запросы) на время команды — до COMMAND_TIMEOUT
            proc_res = await asyncio.to_thread(
                subprocess.run,
                shlex.split(cmd_str),
                capture_output=True,
                text=True,
                timeout=env.command_timeout,
            )
            if proc_res.returncode == 0:
                raw = proc_res.stdout
                source = "cli"
            else:
                cli_err = f"CLI вернула код {proc_res.returncode}: {proc_res.stderr.strip()}"
                first_error = first_error or cli_err
                log_event(
                    f"\033[35m[Metrics]\033[0m {cli_err}",
                    request=request,
                    level='WARNING',
                )
        except Exception as e:
            first_error = first_error or str(e)
            log_event(
                f"\033[35m[Metrics]\033[0m Исключение при вызове CLI: {e}",
                request=request,
                level='WARNING',
            )

    if raw is None:
        err_msg = first_error or "Метрики не получены (нет доступных скриптов или команд)"
        log_event(
            f"\033[35m[Metrics]\033[0m Не удалось собрать метрики: {err_msg}",
            request=request,
            level='ERROR',
        )
        raise HTTPException(status_code=502, detail={"success": False, "error": err_msg})

    if source:
        response.headers["X-Metrics-Source"] = source
    if first_error:
        # Заголовок HTTP — только ASCII без управляющих символов: текст ошибки gRPC многострочный,
        # бывает по-русски, и иначе ответ с уже снятыми (через -reset) метриками падает
        safe_error = first_error.encode('ascii', 'backslashreplace').decode('ascii')
        response.headers["X-Metrics-Error"] = ' '.join(safe_error.split())[:200]

    # 3. Парсинг метрик
    parser_func = meta.get('metrics_parser_code')
    if not parser_func:
        raise HTTPException(
            status_code=500,
            detail={"success": False, "error": "Парсер метрик не настроен для данной ноды"},
        )

    try:
        vpn_users = copy.deepcopy(buffer.buffer_storage.get(body.node_proto_id, {}))
        local_state = buffer.local_state.get(body.node_proto_id, {})
        parsed_res = parser_func(raw, vpn_users, local_state)
        if asyncio.iscoroutine(parsed_res):
            parsed_res = await parsed_res

        if isinstance(parsed_res, tuple) and len(parsed_res) == 2:
            traffic_consuming, troubles = parsed_res
            if troubles:
                log_event(
                    f"\033[35m[Metrics]\033[0m Замечания при парсинге: {troubles}",
                    request=request,
                    level='WARNING',
                )
        else:
            traffic_consuming = parsed_res

        return {"success": True, "users_traffic": traffic_consuming}

    except Exception as e:
        log_event(
            f"\033[35m[Metrics]\033[0m Ошибка парсера метрик: {e}",
            request=request,
            level='ERROR',
        )
        raise HTTPException(
            status_code=500, detail={"success": False, "error": f"Failed to parse stats: {str(e)}"}
        ) from e

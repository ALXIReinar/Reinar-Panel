import subprocess
from typing import Annotated

from fastapi import APIRouter, HTTPException
from fastapi.params import Query

from node_client.api.proto_core.hot_reload_executor import HotReloadExecutor
from node_client.config import env
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
async def get_metrics(body: MetricsSchema):
    try:
        "1. Пробуем получить метрики по Апи ядра"
        if body.metrics_script and body.metrics_port:
            action_res, raw_metrics = await HotReloadExecutor.execute_action_script(
                script=body.metrics_script,
                lib_names=body.core_lib,
                node_ip='127.0.0.1',
                core_api_port=body.metrics_port,
                action='get_metrics',
            )
            if action_res:
                return {'success': True, 'stdout': raw_metrics}

        "2. Получение метрик по команде в cli, если не удалось по скрипту/нет скрипта"
        # xray api statsquery --server=127.0.0.1:{} -pattern "user>>>" -reset
        cmd_str = body.command.format(body.metrics_port)
        # xray api statsquery --server=127.0.0.1:10085 -pattern "user>>>" -reset
        result = subprocess.run(
            cmd_str.split(), # ["xray", "api", "statsquery", "--server=127.0.0.1:10085", "-pattern", '"user>>>"', "-reset"]
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            raise HTTPException(status_code=400, detail={"error": "Failed to get stats", "stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode})

        return {'success': True, 'stdout': result.stdout}

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail={"success": False, "message": f"Команда превысила timeout (10s)", "command": cmd_str})

    except Exception as e:
        raise HTTPException(status_code=500, detail={"success": False, "message": f"Ошибка выполнения команды: {str(e)}", "command": cmd_str})
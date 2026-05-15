import subprocess
from typing import Annotated

from fastapi import APIRouter, HTTPException
from fastapi.params import Query

from node_client.config import env
from node_client.schemas.execute_schema import ExecuteResponseSchema, ExecuteCommandSchema, MetricsSchema, \
    ReadConfigFileSchema, WriteConfigFileSchema

router = APIRouter(prefix='/node', tags=['Execute'])



@router.post('/execute', summary="Выполнить команду на ноде")
async def execute_command(body: ExecuteCommandSchema):
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


@router.get('/config_file/read')
async def read_config_file(query_p: Annotated[ReadConfigFileSchema, Query()]):
    command = f"cat {query_p.file_path}"
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail={"error": "Failed to read config_file", "stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode})

        return {'success': True, 'message': 'Чтение конфиг-файла', 'stdout': result.stdout}

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail={"success": False, "message": f"Команда превысила timeout (10s)", "command": command})

    except Exception as e:
        raise HTTPException(status_code=500, detail={"success": False, "message": f"Ошибка выполнения команды: {str(e)}", "command": command})


@router.put('/config_file/write')
async def write_config_file(query_p: Annotated[WriteConfigFileSchema, Query()]):
    command = f"""cat > {query_p.file_path} <<EOF
{query_p.file_content}
EOF
"""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15
        )
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail={"error": "Failed to write config_file", "stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode})

        return {'success': True, 'message': 'Файл успешно обновлён'}

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail={"success": False, "message": f"Команда превысила timeout (15s)", "command": command})

    except Exception as e:
        raise HTTPException(status_code=500, detail={"success": False, "message": f"Ошибка выполнения команды: {str(e)}", "command": command})


@router.get('/metrics')
async def get_metrics(query_p: Annotated[MetricsSchema, Query()]):
    # xray api statsquery --server=127.0.0.1:{} -pattern "user>>>" -reset

    cmd_str = query_p.command.format(query_p.metrics_port)
    # xray api statsquery --server=127.0.0.1:10085 -pattern "user>>>" -reset

    try:
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
import subprocess
from fastapi import APIRouter
from starlette.responses import JSONResponse

from node_client.config import env
from node_client.schemas.execute_schema import ExecuteResponseSchema, ExecuteCommandSchema, MetricsSchema

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
        return JSONResponse(status_code=408, content={"success": False, "message": f"Команда превысила timeout ({env.command_timeout}s)", "command": body.command})
    
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"Ошибка выполнения команды: {str(e)}", "command": body.command})



@router.get('/metrics')
async def get_metrics(body: MetricsSchema):
    # xray api statsquery --server=127.0.0.1:{} -pattern "user>>>" -reset
    cmd_str = body.command.format(body.metrics_port)

    # xray api statsquery --server=127.0.0.1:10085 -pattern "user>>>" -reset
    result = subprocess.run(
        cmd_str.split(), # ["xray", "api", "statsquery", "--server=127.0.0.1:10085", "-pattern", '"user>>>"', "-reset"]
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        return {"error": "Failed to get stats"}

    return {'success': True, 'stdout': result.stdout}
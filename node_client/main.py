import uvicorn  # noqa: I001
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse

from node_client.api import main_router
from node_client.api.middleware import OnlyAdminAccessMiddleware
from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer
from node_client.config import env
from node_client.exceptions import NodeNotRegisteredError
from node_client.startup import phys_node_sys_init


@asynccontextmanager
async def lifespan(web_app: FastAPI):
    """"""
    "Инициализируем глобальный ConfigWriteBuffer"
    web_app.state.core_buffer = ConfigWriteBuffer(max_batch=env.write_buffer_size, timeout=env.write_buffer_interval)

    "Запрашиваем данные у админки и регистрируем все виртуальные ноды"
    await phys_node_sys_init(web_app.state.core_buffer)

    try:
        yield
    finally:
        await web_app.state.core_buffer.stop()


app = FastAPI(lifespan=lifespan)

app.include_router(main_router)
app.add_middleware(OnlyAdminAccessMiddleware)


@app.exception_handler(NodeNotRegisteredError)
async def node_not_registered_handler(request: Request, exc: NodeNotRegisteredError):
    """Глобальный обработчик: нода не зарегистрирована → 428 Precondition Required"""
    return JSONResponse(
        status_code=428,
        content={
            "success": False,
            "message": "нода не зарегистрирована в нод-клиенте, выполните реинициализацию",
            "node_proto_id": exc.node_proto_id,
        },
    )


if __name__ == '__main__':
    # uvicorn.run('node_client.main:app', log_config=None, host="0.0.0.0", port=env.node_port, workers=1)
    uvicorn.run('node_client.main:app', host="0.0.0.0", port=env.node_port, workers=1)

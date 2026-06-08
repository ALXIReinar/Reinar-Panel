import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from node_client.api import main_router
from node_client.api.middleware import OnlyAdminAccessMiddleware
from node_client.api.proto_core.write_behind_caching_file import ConfigWriteBuffer
from node_client.config import env


@asynccontextmanager
async def lifespan(web_app: FastAPI):
    """"""
    "Инициализируем глобальный ConfigWriteBuffer"
    web_app.state.core_buffer = ConfigWriteBuffer(max_batch=env.write_buffer_size, timeout=env.write_buffer_interval)

    try:
        yield
    finally:
       await web_app.state.core_buffer.stop()


app = FastAPI(default_response_class=ORJSONResponse, lifespan=lifespan)

app.include_router(main_router)
app.add_middleware(OnlyAdminAccessMiddleware)

if __name__ == '__main__':
    # uvicorn.run('node_client.main:app', log_config=None, host="0.0.0.0", port=env.node_port, workers=1)
    uvicorn.run('node_client.main:app', host="0.0.0.0", port=env.node_port, workers=1)

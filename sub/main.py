import uvicorn
from contextlib import asynccontextmanager

from asyncpg import create_pool
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from sub.config import pool_settings, env


@asynccontextmanager
async def lifespan(web_app: FastAPI):
    """"""
    "Соединение с БД"
    web_app.state.pg_pool = await create_pool(**pool_settings)

    try:
        yield
    finally:
       await web_app.state.core_buffer.stop()
    

app = FastAPI(default_response_class=ORJSONResponse, lifespan=lifespan)



if __name__ == '__main__':
    uvicorn.run('sub.main:app', log_config=None, host="0.0.0.0", port=env.uvicorn_port, workers=env.uvicorn_workers)

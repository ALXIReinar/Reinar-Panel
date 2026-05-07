import uvicorn
from fastapi import FastAPI

from node_client.api import main_router
from node_client.config import env

app = FastAPI()

app.include_router(main_router)


if __name__ == '__main__':
    uvicorn.run('node_client.main:app', log_config=None, host="0.0.0.0", port=env.node_port, workers=env.uvicorn_workers)

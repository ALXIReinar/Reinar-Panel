"""
Второстепенные помощники эндпоинтов физических и виртуальных нод
"""

from aiohttp import ClientSession

from web.utils.anything import NodeUris


async def push_reinit(
    aio_http: ClientSession,
    private_ip: str,
    api_port: int,
    node_proto_ids: list[int],
) -> tuple[int, dict]:
    """
    Просит нод-клиент физической ноды реинициализировать виртуальные ноды (POST /api/v1/server/node/reinit)

    Только приватный адрес (WireGuard): публичный адрес нужен лишь сервису подписок для ссылок пользователей,
    а командам админки нод-клиента в обход приватной сети ходить нельзя.

    Args:
        aio_http: сессия командного центра (NodeExecAiohttpDep)
        private_ip: приватный IP физической ноды
        api_port: порт нод-клиента
        node_proto_ids: ID виртуальных нод; пустой список = все ноды физической ноды

    Таймаут — сессии (30 с); короче — оборачивайте вызов в asyncio.timeout()

    Returns:
        tuple: (HTTP-статус ответа нод-клиента, тело ответа)

    Raises:
        aiohttp.ClientError, TimeoutError: нод-клиент недоступен или ответил не JSON
    """
    url = f'http://{private_ip}:{api_port}{NodeUris.reinit}'
    async with aio_http.post(url, json={'node_proto_ids': node_proto_ids}) as resp:
        return resp.status, await resp.json()

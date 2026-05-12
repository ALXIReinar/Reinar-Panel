import secrets

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Send, Receive, Scope

from node_client.config import env


class OnlyAdminAccessMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] not in {"http",}:
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        client_ip = client[0] if client else ''

        if not secrets.compare_digest(client_ip, env.admin_panel_private_ip):
            response = JSONResponse(status_code=403, content='Forbidden')
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
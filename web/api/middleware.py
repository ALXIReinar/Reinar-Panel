from datetime import datetime, UTC
import time

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Scope, Receive, Send, ASGIApp

from web.config_dir.config import env
from web.data.postgres import PgSql
from web.utils.anything import get_client_ip
from web.utils.jwt_factory import get_jwt_decode_payload, reissue_aT
from web.utils.logger_config import log_event


class ASGILoggingMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope['type'] not in {'http',}:
            await self.app(scope, receive, send)
            return

        # >>>>> Работает ли эта конструкция????. Не должна, так как receive можно использовать только один раз => при ответе через self.app будет исключение
        request = Request(scope, receive=receive)

        # client = scope.get("client") # Альтернатива для получения ip
        # client_host = client[0] if client else ''
        ip = get_client_ip(request)
        request.state.client_ip = ip

        start = time.perf_counter()
        status_code = 500  # По умолчанию, если что-то пойдет не так

        async def send_wrapper(message):
            nonlocal status_code
            if message['type'] == 'http.response.start':
                status_code = message['status']
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start

            "Логируем для мониторинга"
            if env.app_mode != 'local' and request.url.path != '/api/v1/healthcheck':
                log_event(f'HTTP \033[33m{request.method}\033[0m {request.url.path}', request=request,
                          http_status=status_code, response_time=round(duration, 4))
            if duration > 7.0:
                log_event(f'Долгий ответ | {duration: .4f}', request=request, level='WARNING')


class AuthUXASGIMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope['type'] not in {'http', 'websocket'}:
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        now = datetime.now(UTC)

        request.state.admin_id = 0
        request.state.session_id = '0'

        url = request.url.path
        "Обращения Сервера(под-адрес /server) доступен для allowed_ips"
        if request.state.client_ip in env.allowed_ips:
            await self.app(scope, receive, send)
            return

        "Не нуждаются в авторизации, Если юрл в белом списке"
        if any(url.startswith(prefix) for prefix in ('/api/v1/public', )):
            await self.app(scope, receive, send)
            return


        encoded_access_token = request.cookies.get('access_token')
        if (access_token:= get_jwt_decode_payload(encoded_access_token)) == 401:
            # невалидный аксес_токен
            log_event("Попытка подмены access_token", request=request, level='CRITICAL')
            response =  JSONResponse(status_code=401, content={'message': 'Нужна повторная аутентификация'})
            await response(scope, receive, send)
            return

        if datetime.fromtimestamp(access_token['exp'], tz=UTC) < now:
            # аксес_токен ИСТЁК
            "процесс выпуска токена"
            async with request.app.state.pg_pool.acquire() as conn:
                db = PgSql(conn)
                refresh_token = request.cookies.get('refresh_token')
                new_token = await reissue_aT(access_token, refresh_token, db)

            if new_token == 401:
                # рефреш_токен НЕ ВАЛИДЕН
                log_event(f"Попытка подмены refresh_token | s_id: {access_token.get('s_id', '')}; admin_id: {access_token.get('sub', '')}",
                          request=request, level='CRITICAL')
                response = JSONResponse(status_code=401, content={'message': 'Нужна повторная аутентификация'})
                await response(scope, receive, send)
                return

            request.state.new_a_t = new_token

        request.state.admin_id = int(access_token['sub'])
        request.state.session_id = access_token['s_id']
        await self.app(scope, receive, send)

from datetime import datetime, UTC

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Scope, Receive, Send, ASGIApp

from web.config_dir.config import env
from web.data.postgres import PgSql
from web.utils.anything import get_client_ip_by_scope
from web.utils.jwt_factory import get_jwt_decode_payload, reissue_aT
from web.utils.logger_config import log_event

import time


class ASGILoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] not in {'http', 'websocket'}:
            await self.app(scope, receive, send)
            return


        scope.setdefault('state', {})

        # Используем вашу логику получения IP из заголовков (через scope)

        ip = get_client_ip_by_scope(scope)

        scope['state']['client_ip'] = ip  # Теперь это будет доступно в request.state.client_ip

        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message['type'] == 'http.response.start':
                status_code = message['status']
            await send(message)

        try:
            # Передаем оригинальный receive, мы его не трогали
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start
            path = scope.get('path', '')
            method = scope.get('method', '')

            # Логика логирования
            if env.app_mode != 'local' and path != '/api/v1/healthcheck':
                # Здесь можно создать временный request только для лога,
                # так как выполнение уже завершено
                log_event(f'HTTP {method} {path}', http_status=status_code, response_time=round(duration, 4))

            if duration > 7.0:
                log_event(f'Долгий ответ | {duration: .4f}', level='WARNING')


class AuthUXASGIMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope['type'] not in {'http', 'websocket'}:
            await self.app(scope, receive, send)
            return

        # Инициализируем state, если его нет
        scope.setdefault('state', {})
        scope['state']['admin_id'] = 0
        scope['state']['session_id'] = '0'

        url = scope.get('path', '')

        # ВАЖНО: LoggingMiddleware должна стоять РАНЬШЕ этой в списке middleware
        client_ip = scope['state'].get('client_ip')

        "Полный доступ от Выбранных ip"
        if client_ip in env.allowed_ips:
            await self.app(scope, receive, send)
            return

        "Не нуждаются в авторизации, Если юрл в белом списке"
        if any(url.startswith(prefix) for prefix in ('/api/v1/public', )):
            await self.app(scope, receive, send)
            return

        request = Request(scope)  # Используем только для cookie
        encoded_access_token = request.cookies.get('access_token')

        "Проверка Access Token"
        if (access_token:= get_jwt_decode_payload(encoded_access_token)) == 401:
            # невалидный аксес_токен
            log_event("Попытка подмены access_token", request=request, level='CRITICAL')
            response =  JSONResponse(status_code=401, content={'success': False, 'message': 'Нужна повторная аутентификация'})
            await response(scope, receive, send)
            return

        "Перевыпуск Access Token"
        now = datetime.now(UTC)
        if datetime.fromtimestamp(access_token['exp'], tz=UTC) < now:
            # аксес_токен ИСТЁК
            "процесс выпуска токена"
            app_instance = scope['app']
            async with app_instance.state.pg_pool.acquire() as conn:
                db = PgSql(conn)
                refresh_token = request.cookies.get('refresh_token')
                new_token = await reissue_aT(access_token, refresh_token, db)

            if new_token == 401:
                # рефреш_токен НЕ ВАЛИДЕН
                log_event(f"Попытка подмены refresh_token | s_id: {access_token.get('s_id', '')}; admin_id: {access_token.get('sub', '')}",
                          request=request, level='CRITICAL')
                response = JSONResponse(status_code=401, content={'success': False, 'message': 'Нужна повторная аутентификация'})
                await response(scope, receive, send)
                return

            scope['state']['new_a_t'] = new_token

        scope['state']['admin_id'] = int(access_token['sub'])
        scope['state']['session_id'] = access_token['s_id']

        await self.app(scope, receive, send)
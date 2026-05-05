from fastapi import APIRouter, Response, Request
from starlette.responses import JSONResponse

from web.data.postgres import PgSqlDep
from web.config_dir.config import encryption
from web.schemas.cookie_settings_schema import AccToken, RtToken, JWTCookieDep
from web.schemas.admins_schema import TokenPayloadSchema, AdminRegSchema, AdminLogInSchema, UpdatePasswSchema
from web.utils.anything import hide_log_param
from web.utils.jwt_factory import issue_aT_rT
from web.utils.logger_config import log_event


router = APIRouter(tags=['admins👤'])


@router.post('/server/admins/sign_up', summary="Регистрация")
async def registration_user(creds: AdminRegSchema, db: PgSqlDep, request: Request):
    insert_attempt = await db.admins.reg_admin(creds.login, creds.passw)

    if not insert_attempt:
        log_event(f"Пользователь с email: {hide_log_param(creds.login)} Уже существует", request=request,
                  level='WARNING')
        return JSONResponse(status_code=204, content={"success": False, "message": 'Такой пользователь уже существует'})

    log_event(f"Новый пользователь! email: {hide_log_param(creds.login)}", request=request)
    return {'success': True, 'message': 'Пользователь создан'}


@router.post('/public/admins/login', summary="Вход в аккаунт")
async def log_in(creds: AdminLogInSchema, db: PgSqlDep, request: Request):
    db_user = await db.admins.select_admin(creds.login)

    if db_user and encryption.verify(creds.passw, db_user['passw']):
        token_schema = TokenPayloadSchema(
            id=db_user['id'],
            user_agent=request.headers.get('user-agent'),
            ip=request.state.client_ip,
        )
        access_token, refresh_token = await issue_aT_rT(db, token_schema)

        log_event("Пользователь Вошёл в акк | user_id: %s", db_user['id'], request=request)
        json_response = JSONResponse(status_code=200, content={'success': True, 'message': 'Успешная авторизация!'})

        "Ставим куки"
        json_response.set_cookie('access_token', access_token, **AccToken().model_dump())
        json_response.set_cookie('refresh_token', refresh_token, **RtToken().model_dump())
        return json_response

    log_event(f"Пользователь с email: {hide_log_param(creds.login)} Не смог войти", request=request, level='WARNING')
    return JSONResponse(status_code=401, content='Требуется повторная аутентификация')


@router.put('/private/admins/logout')
async def log_out(request: Request, response: Response, db: PgSqlDep, _: JWTCookieDep):
    await db.auth.session_termination(request.state.user_id, request.state.session_id)
    response.delete_cookie('access_token')
    response.delete_cookie('refresh_token')
    log_event("Пользователь разлогинился | user_id: %s; s_id: %s", request.state.user_id, request.state.session_id,
              request=request)
    return {'success': True, 'message': 'Пользователь вне аккаунта'}


@router.post('/private/admins/seances', summary='Все Устройства аккаунта')
async def show_seances(request: Request, db: PgSqlDep, _: JWTCookieDep):
    log_event("Запрос всех Устройств с акка | user_id: %s; s_id: %s", request.state.user_id, request.state.session_id,
              request=request, level='INFO')
    seances = await db.auth.all_seances_user(request.state.user_id, request.state.session_id)
    return {'seances': seances}


@router.put('/server/admins/passw/set_new_passw')
async def reset_password(update_secrets: UpdatePasswSchema, db: PgSqlDep, request: Request):
    hashed_passw = encryption.hash(update_secrets.passw)
    await db.admins.set_new_passw(update_secrets.user_id, hashed_passw)
    log_event(f"Юзер сменил Пароль | user_id: {update_secrets.user_id}", request=request, level='CRITICAL')
    return {'success': True, 'message': 'Пароль обновлён!'}
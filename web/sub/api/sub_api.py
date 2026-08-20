import base64
from urllib.parse import urlunsplit, quote, urlsplit, urlencode, parse_qsl
from typing import Annotated

from fastapi import APIRouter, Response, Path
from pydantic import IPvAnyAddress
from starlette.requests import Request

from web.sub.api.handlers.prepare_func import error_messages_for_client, process2vpn_client_format, create_vpn_like_user
from web.sub.config_dir.logger_config import log_event
from web.sub.config_dir.config import env
from web.sub.data.postgres import PgSqlDep
from web.sub.sandbox.script_executor import ScriptExecutor
from web.sub.schemas.sub_robo_schema import SubUrlSchema

router = APIRouter(prefix='/api/v1/public', tags=['Subscriptions Service'])


@router.get('/sub/{b64_id}')
async def sub(params: Annotated[SubUrlSchema, Path()], db: PgSqlDep, request: Request):
    """
    Подумать над тем, чтобы передавать список локаций в скрипт обработки конфиг-ссылок перед выдачей пользователю

    В соображениях производительности
    Лучше 100 ссылок обработать за один запуск sandbox, чем 100 раз запускать эту самую песочницу
    """
    sub_meta, config_data = await db.sub.get_sub_links(params.b64_id)

    "Подписка пользователя деактивирована/не существует"
    if not sub_meta:
        messages = error_messages_for_client(
            'Вы израсходовали лимит трафика за день. Обновите ваш план',
            f'Продлить подписку в нашем боте {env.tg_bot_link}',
        )
        log_event(f'Подписка приостановлена/не найдена | b64_id: \033[31m{params.b64_id}\033[0m', request=request, level='WARNING')
        return Response(content=process2vpn_client_format(messages), media_type='text/plain')

    "Обрабатываем каждую ссылку через кастомный скрипт"
    ready_config_links, errors = [], []
    for proto_user_conf in config_data:
        ok, user_super_obj = create_vpn_like_user(
            user_uuid=sub_meta['user_uuid'],
            user_sub_id=sub_meta['user_sub_id'],
            required_user_data_obj=proto_user_conf['required_user_data_obj'],
            constant_user_data_obj=proto_user_conf['constant_user_data_obj'],
            constant_node_data_obj=proto_user_conf['constant_node_data_obj'],
        )
        if not ok:
            log_event(f'Не удалось Сформировать суперобъект из шаблонов | err: {user_super_obj}; node_proto_id: \033[35m{proto_user_conf['node_proto_id']}\033[0m; req_u_data_obj: {proto_user_conf["required_user_data_obj"]}; const_u_data_obj: {proto_user_conf["constant_user_data_obj"]}; const_node_data_obj: {proto_user_conf["constant_node_data_obj"]}', request=request, level='WARNING')
            errors.append((500, "Не удалось сформировать суперобъект"))
            continue

        success, res = await ScriptExecutor.executing_link_processing(
            sub_prepare_script=proto_user_conf['sub_prepare_script'],
            required_libs=proto_user_conf['required_libs'],
            user_obj=user_super_obj,
            config_link=proto_user_conf['config_link'],
        )

        "Исключение при обработке. Или ссылки для пользователя"
        if not success:
            log_event(f'Не смогли выдать локацию из подписки | user_id: \033[34m{sub_meta['user_id']}\033[0m; sub_id: \033[33m{sub_meta['sub_plan_id']}\033[0m; node_proto_id: \033[35m{proto_user_conf['node_proto_id']}\033[0m; vnodes_sub_plans_id: {proto_user_conf['sub_node_id']}', request=request, level='CRITICAL')
            errors.append(res)
        else:
            "Квотим ссылку, заменяем проблемные для url символы"
            "1. Разбираем URL на компоненты и безопасно кодируем"
            parsed = urlsplit(res)

            # parse_qsl разбивает строку "a=1&b=2" на список кортежей [('a', '1'), ('b', '2')]
            # urlencode собирает это обратно в безопасный вид, энкодит все спецсимволы
            safe_query = urlencode(parse_qsl(parsed.query))

            # quote энкодит только fragment (#MyNode -> #My%20Node)
            safe_fragment = quote(parsed.fragment)

            "1.1. Обрабатываем netloc через punycode (если это домен)"
            # TODO: Подумать, может, можно брать node___title и node___address в самом конце и подставлять прямо на этом этапе??
            # Такая обработка выглядит болезненно и ненадёжно
            netloc = parsed.netloc
            if netloc:
                # Извлекаем хост из netloc (может содержать порт: host:port или user@host:port)
                # Для простоты обрабатываем весь netloc через punycode если это не IP
                from pydantic import IPvAnyAddress
                
                # Пытаемся извлечь хост из netloc
                if '@' in netloc:
                    # Формат: user@host:port
                    user_part, host_port = netloc.rsplit('@', 1)
                else:
                    user_part = None
                    host_port = netloc
                
                # Разделяем хост и порт
                if ':' in host_port and not host_port.startswith('['):  # IPv6 в квадратных скобках не трогаем
                    host, port = host_port.rsplit(':', 1)
                else:
                    host = host_port
                    port = None
                
                # Проверяем является ли хост IP адресом
                try:
                    IPvAnyAddress(host.strip('[]'))  # IPv6 может быть в []
                    # Это IP - оставляем как есть
                    safe_netloc = netloc
                except ValueError:
                    # Это домен - применяем punycode
                    try:
                        safe_host = host.encode('idna').decode('ascii')
                    except (UnicodeError, UnicodeDecodeError):
                        # На случай странных символов используем quote
                        safe_host = quote(host)
                    
                    # Собираем netloc обратно
                    if port:
                        safe_netloc = f"{safe_host}:{port}"
                    else:
                        safe_netloc = safe_host
                    
                    if user_part:
                        safe_netloc = f"{user_part}@{safe_netloc}"
            else:
                safe_netloc = netloc

            "2. Собираем итоговую ссылку"
            final_url = urlunsplit((
                parsed.scheme,
                safe_netloc,
                parsed.path,
                safe_query,
                safe_fragment
            ))
            ready_config_links.append(final_url)

    if errors:
        log_event(f'Не все конфиги удалось обработать | user_uuid: \033[35m{sub_meta['user_uuid']}\033[0m; errors: \033[37m{errors}\033[0m', level='WARNING')

    "В случае, если ни одна локация не сгенерировалась"
    if not ready_config_links:
        ready_config_links = error_messages_for_client('Приносим свои извинения за технические неполадки', 'Мы уже знаем об этом и решаем проблему')

    "Готовим ответ для Впн клиента"
    user_traffic, sub_plan_limit = sub_meta['traffic_used_day_mb'], sub_meta['sub_plan_limit']
    exp_date = int(sub_meta['expire_date'].timestamp()) if sub_meta['expire_date'] is not None else 0

    response = Response(
        content=process2vpn_client_format(ready_config_links),
        media_type='text/plain',
        headers={
            "Subscription-Userinfo": f"upload=0; download={user_traffic}; total={sub_plan_limit}; expire={exp_date}",
            'profile-title': f"base64:{base64.b64encode(sub_meta['title'].encode()).decode()}",
            "profile-update-interval": env.subscription_update_interval,  # Обновлять каждые 12 часов
            "profile-web-page-url": env.tg_bot_link,
            "announce": f"base64:{base64.b64encode(sub_meta['description'].encode()).decode()}",
        }
    )
    return response

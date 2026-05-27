import base64
import json
import math
import re
import urllib.parse
from typing import Annotated

from fastapi import APIRouter, Response, Path
from starlette.requests import Request

from web.sub.config_dir.logger_config import log_event
from web.sub.config_dir.config import env
from web.sub.data.postgres import PgSqlDep
from web.sub.schemas import SubUrlSchema

router = APIRouter(tags=['Subscriptions Service'])

@router.get('/healthcheck')
def healthcheck():
    return {'status': True, 'service': 'sub-service'}



@router.get('/sub/{b64_id}')
async def sub(params: Annotated[SubUrlSchema, Path()], db: PgSqlDep, request: Request):
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
        res = executing_link_processing(
            sub_prepare_script=proto_user_conf['sub_prepare_script'],
            required_libs=proto_user_conf['required_libs'],
            user_uuid=sub_meta['user_uuid'],
            config_link=proto_user_conf['config_link'],
            user_id=sub_meta['user_id'],
        )

        "Исключение при обработке. Или ссылки для пользователя"
        if not res[0]:
            log_event(f'Не смогли выдать локацию из подписки | user_id: \033[34m{sub_meta['user_id']}\033[0m; sub_id: \033[33m{sub_meta['sub_plan_id']}\033[0m; node_proto_id: \033[35m{proto_user_conf['node_proto_id']}\033[0m; vnodes_sub_plans_id: {proto_user_conf['sub_node_id']}', request=request, level='CRITICAL')
            errors.append((res[1], res[2]))
        else:
            ready_config_links.append(res[1])

    if errors:
        log_event(f'Не все конфиги удалось обработать | user_uuid: \033[35m{sub_meta['user_uuid']}\033[0m; errors: \033[37m{errors}\033[0m', level='WARNING')

    "В случае, если ни одна локация не сгенерировалась"
    if not ready_config_links:
        ready_config_links = error_messages_for_client('Приносим свои извинения за технические неполадки', 'Мы уже в курсе и решаем эту проблему')

    "Готовим ответ для Впн клиента"
    user_traffic, sub_plan_limit, exp_date = sub_meta['traffic_used_day_mb'], sub_meta['sub_plan_limit'], int(sub_meta['expire_date'].timestamp())
    response = Response(
        content=process2vpn_client_format(ready_config_links),
        media_type='text/plain',
        headers={
            "Subscription-Userinfo": f"upload=0; download={user_traffic}; total={sub_plan_limit}; expire={exp_date}",
            'profile-title': sub_meta['title'], # Только латиница
            "profile-update-interval": env.subscription_update_interval,  # Обновлять каждые 12 часов
            "profile-web-page-url": env.tg_bot_link,
            "announce": f"base64:{base64.b64encode(sub_meta['description'].encode()).decode()}",
        }
    )
    return response



def error_messages_for_client(*messages: str):
    tmp = 'vless://00000000-0000-0000-0000-000000000000@127.0.0.1:443?encryption=none#{}'
    return [tmp.format(urllib.parse.quote(msg)) for msg in messages]

def process2vpn_client_format(any_obj: str | list[str], description: str = None) -> str:
    if isinstance(any_obj, list):
        any_obj = '\n'.join(any_obj)
    if description is not None:
        any_obj = f"#note:{urllib.parse.quote(description)}\n{any_obj}"
    return base64.b64encode(any_obj.encode()).decode()


def executing_link_processing(sub_prepare_script: str, required_libs: str, user_uuid: str, config_link: str, user_id: int):
    depend_libs = {lib_name.strip(): lib_name.strip() for lib_name in required_libs.split(',')}
    local_scope = {}
    global_scope = {
        "json": json,
        "re": re,
        "math": math,
        # добавляем либы, выбранные пользователем
        **depend_libs,
        # Запрещаем опасные встроенные функции типа open, eval, import
        "__builtins__": {
            "int": int, "str": str, "float": float, "list": list, "dict": dict,
            "set": set, "len": len, "range": range, "round": round, "print": print,
            "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
            "Exception": Exception, "ValueError": ValueError
        }
    }

    try:
        exec(sub_prepare_script, global_scope, local_scope)
        # Вызываем функцию prepare_sub, которую юзер написал в шаблоне
        return True, local_scope['prepare_sub'](user_uuid, config_link)

    except ImportError as ie:
        log_event(f"Библиотека, указанная пользователем не установлена в окружении | user_id: \033[31m{user_id}\033[0m; lib_name: \033[36m{ie.name}\033[0m", level='ERROR')
        return False, 500, "Сервер не смог обработать список локаций в подписке"

    except Exception as e:
        log_event(f'Упал скрипт парсинга stdout метрик | user_id: \033[31m{user_id}\033[0m; code: {sub_prepare_script}; exception: {e}', level='CRITICAL')
        return False, 500, "Ошибка сервера"
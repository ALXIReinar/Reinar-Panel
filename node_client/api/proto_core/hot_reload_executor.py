import asyncio
import importlib
import json
import math
import re
from collections import defaultdict
from typing import Literal

import flatten_json
import jmespath
import orjson

from node_client.logger_config import log_event

# Принудительная очистка кэша - для библиотек из шаблонов-скриптов
importlib.invalidate_caches()

class HotReloadExecutor:
    """Выполнение Python скриптов для hot-reload операций"""
    
    @staticmethod
    async def execute_action_script(
            script: str,
            lib_names: str,
            node_ip: str,
            core_api_port: int,
            action: Literal["add_user", "delete_user", "bulk_delete_users", "get_metrics"],
            custom_params: dict | None = None,
            user_obj: dict | str | list[dict] = None,

    ) -> tuple[bool, str]:
        """
        Выполняет скрипт добавления пользователя через API
        
        Args:
            script: Python код с функцией add_user()
            lib_names: Имя библиотеки для импорта (grpcio, requests)
            user_obj: Объект пользователя
            node_ip: IP ноды
            core_api_port: Порт АПИ ядра протокола
            custom_params: Зависимости для скрипта, которые идут отдельно от объекта пользователя

        Returns:
            tuple[success, message]

        """
        if custom_params is None:
            custom_params = {}
        try:

            "Создаём локальное окружение для выполнения скрипта"
            user_libs = {lib_name: importlib.import_module(lib_name) for lib_name in lib_names} # Подгружаем библиотеки пользователя
            local_scope = {}
            global_scope = {
                **user_libs,
                "json": json,
                "asyncio": asyncio,
                "orjson": orjson,
                "re": re,
                "math": math,
                "defaultdict": defaultdict,
                "jmespath": jmespath,
                "flatten_json": flatten_json,
                # Запрещаем опасные встроенные функции типа open, eval, import
                "__builtins__": {
                    "int": int, "str": str, "float": float, "list": list, "dict": dict,
                    "set": set, "len": len, "range": range, "round": round, "print": print,
                    "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
                    "Exception": Exception, "ValueError": ValueError
                }
            }
            # Выполняем скрипт
            exec(script, global_scope, local_scope)

            "Вызываем функцию из скрипта"
            action_user_func = (
                    local_scope.get('add_user') or
                    local_scope.get('delete_user') or
                    local_scope.get('bulk_delete_users') or
                    local_scope.get('get_metrics')
            )
            if not action_user_func:
                return False, "Ни одна из функций: (add_user, delete_user, bulk_delete_users) - не найдена в скрипте"

            "Подбираем набор аргументов исходя от действия скрипта"
            args_func_map = {
                "add_user": (user_obj, node_ip, core_api_port, custom_params),
                "delete_users": (user_obj, node_ip, core_api_port, custom_params),
                "bulk_delete_users": (user_obj, node_ip, core_api_port, custom_params),
                "get_metrics": (node_ip, core_api_port, custom_params),
            }
            result = action_user_func(*args_func_map[action])

            "Если async"
            if asyncio.iscoroutine(result):
                result = await result

            log_event(f"Hot-reload успешно выполнен для пользователя | user_obj: \033[37m{user_obj}\033[0m")
            return True, f"Hot-reload успешно. script_result: {result}"
            
        except ImportError as e:
            error_msg = f"Библиотека {lib_names} не найдена | original_exception: {e}"
            log_event(error_msg, level='CRITICAL')
            return False, error_msg
            
        except Exception as e:
            error_msg = f"Ошибка выполнения action_script скрипта | exception: {e}"
            log_event(error_msg, level='CRITICAL')
            return False, error_msg

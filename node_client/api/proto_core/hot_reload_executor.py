import asyncio
import importlib
import json
import math
import re
import traceback
from collections import defaultdict
from typing import Literal, Callable, Any

import flatten_json
import jmespath
import orjson

from node_client.logger_config import log_event

# Принудительная очистка кэша - для библиотек из шаблонов-скриптов
importlib.invalidate_caches()

class HotReloadExecutor:
    """Выполнение Python скриптов для hot-reload операций"""
    base_globals = {
        "json": json,
        "asyncio": asyncio,
        "orjson": orjson,
        "re": re,
        "math": math,
        "defaultdict": defaultdict,
        "jmespath": jmespath,
        "flatten_json": flatten_json,
    }
    safe_builtins = {
        "int": int, "str": str, "float": float, "list": list, "dict": dict,
        "set": set, "len": len, "range": range, "round": round, "print": print,
        "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
        "isinstance": isinstance, "type": type, "dir": dir, "all": all, "any": any,
        "Exception": Exception, "ValueError": ValueError, "KeyError": KeyError,
        "NameError": NameError, "TypeError": TypeError, "AttributeError": AttributeError,
    }

    @classmethod
    def _prepare_globals(cls, lib_names: str | None = None) -> dict[str, Any]:
        """Формирует изолированный global_scope для конкретного запуска"""
        # Shallow copy словарь — это предотвратит кашу при замусоривании скоупа скриптом
        g_scope = cls.base_globals.copy()
        g_scope["__builtins__"] = cls.safe_builtins.copy()

        if lib_names:
            for lib in lib_names.split(','):
                lib_clean = lib.strip()
                if lib_clean:
                    g_scope[lib_clean] = importlib.import_module(lib_clean)

        return g_scope

    @classmethod
    async def execute_action_script(
            cls,
            script: str,
            lib_names: str | None,
            node_ip: str,
            core_api_port: int,
            action: Literal["bulk_delete_users", "bulk_add_users", "get_metrics"],
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
            local_scope = {}
            global_scope = cls._prepare_globals(lib_names)

            # Выполняем скрипт
            exec(script, global_scope, local_scope)

            "Вызываем функцию из скрипта"
            action_user_func = (
                    local_scope.get('bulk_delete_users') or
                    local_scope.get('bulk_add_users') or
                    local_scope.get('get_metrics') or
                    local_scope.get('parse')
            )
            if not action_user_func:
                msg = "Ни одна из функций: (bulk_delete_users, bulk_add_users, get_metrics, parse) - не найдена в скрипте"
                log_event(msg, level='ERROR')
                return False, msg

            "Подбираем набор аргументов исходя от действия скрипта"
            args_func_map = {
                "user_core_operation": (user_obj, node_ip, core_api_port, custom_params), # Подходит для бульк/обычных вставок/удалений
                "get_metrics": (node_ip, core_api_port, custom_params),
            }
            result = action_user_func(*args_func_map[action])

            "Если async"
            if asyncio.iscoroutine(result):
                result = await result

            log_event(f"Hot-reload успешно выполнен для пользователя | user_obj: \033[37m{user_obj}\033[0m")
            return True, result
            
        except ImportError as e:
            log_event(f"\033[31mОШИБКА ИМПОРТА БИБЛИОТЕКИ\033[0m\nБиблиотека: {lib_names}\nAction: {action}\nДетали: {str(repr(e))}", level='CRITICAL')
            return False, f"Библиотека {lib_names} не найдена. Убедитесь что она установлена в виртуальном окружении."
            
        except SyntaxError as e:
            script_lines = script.split('\n')
            error_line = script_lines[e.lineno - 1] if e.lineno and e.lineno <= len(script_lines) else "???"

            log_event(f"\033[31mСИНТАКСИЧЕСКАЯ ОШИБКА В СКРИПТЕ\033[0m\nAction: {action}\nСтрока {e.lineno}: {error_line}\nОшибка: {e.msg}\nПозиция: {' ' * (e.offset - 1) if e.offset else ''}^\n", level='CRITICAL')

            return False, f"Синтаксическая ошибка в скрипте: {e.msg} (строка {e.lineno})"
            
        except Exception as e:
            tb_str = traceback.format_exc()

            log_event(f"\033[31mОШИБКА ВЫПОЛНЕНИЯ СКРИПТА\033[0m\nAction: {action}\nБиблиотеки: {lib_names}\nТип ошибки: {type(e).__name__}\nСообщение: {str(e)}\n\nTraceback:\n{tb_str}\n", level='CRITICAL')
            return False, f"Ошибка выполнения скрипта ({type(e).__name__}): {str(e)}"


    @classmethod
    def get_compiled_func(cls, func_script: str, func_name: str, libs: str | None = None) -> Callable:
        local_scope = {}
        global_scope = cls._prepare_globals(libs)

        exec(func_script, global_scope, local_scope)

        "Достаём рабочую функцию"
        compiled_func = local_scope.get(func_name)
        if not compiled_func:
            msg = f"Функция ней найдена в скрипте | func_name: \033[33m{func_name}\033[0m; \033[36m{func_script[:150]}\033[0m"
            log_event(msg, level='ERROR')
            raise ValueError(msg)

        return compiled_func
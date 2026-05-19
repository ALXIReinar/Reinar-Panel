import importlib
import json
import math
import re
import sys
from collections import defaultdict
from typing import Any

import flatten_json
import jmespath
import orjson

from node_client.logger_config import log_event


class HotReloadExecutor:
    """Выполнение Python скриптов для hot-reload операций"""
    
    @staticmethod
    async def execute_add_script(
            script: str, lib_name: str, user_obj: dict, proto_config: dict, node_ip: str, proto_port: int
    ) -> tuple[bool, str]:
        """
        Выполняет скрипт добавления пользователя через API
        
        Args:
            script: Python код с функцией add_user()
            lib_name: Имя библиотеки для импорта (grpcio, requests)
            user_obj: Объект пользователя
            proto_config: Конфиг протокола
            node_ip: IP ноды
            proto_port: Порт протокола
            
        Returns:
            tuple[success, message]
        """
        try:

            "Создаём локальное окружение для выполнения скрипта"
            local_scope = {}
            global_scope = {
                lib_name: importlib.import_module(lib_name),
                "json": json,
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
            
            "Вызываем функцию add_user из скрипта"
            add_user_func = local_scope['add_user'](user_obj, proto_config, node_ip, proto_port)
            result = add_user_func(user_obj, proto_config, node_ip, proto_port)
            
            "Если async"
            if hasattr(result, '__await__'):
                result = await result
            
            log_event(f"Hot-reload ADD успешно выполнен для пользователя | uuid: {user_obj.get('id', 'unknown')}", level='INFO')
            return True, "Hot-reload добавление успешно"
            
        except ImportError as e:
            error_msg = f"Библиотека {lib_name} не найдена: {e}"
            log_event(error_msg, level='CRITICAL')
            return False, error_msg
            
        except Exception as e:
            error_msg = f"Ошибка выполнения add_user скрипта: {e}"
            log_event(error_msg, level='CRITICAL')
            return False, error_msg


    @staticmethod
    async def execute_delete_script(
        script: str,
        lib_name: str,
        user_identifier: str,
        config: dict,
        node_ip: str,
        proto_port: int
    ) -> tuple[bool, str]:
        """
        Выполняет скрипт удаления пользователя через API
        
        Args:
            script: Python код с функцией **delete_user()**
            lib_name: Имя библиотеки для импорта
            user_identifier: Идентификатор пользователя (UUID или email)
            config: Конфиг протокола
            node_ip: IP ноды
            proto_port: Порт протокола
            
        Returns:
            tuple[success, message]
        """
        try:
            "Создаём локальное окружение для выполнения скрипта"
            local_scope = {}
            global_scope = {
                lib_name: importlib.import_module(lib_name),
                "json": json,
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
            "Выполняем скрипт"
            exec(script, global_scope, local_scope)
            
            "Вызываем функцию delete_user из скрипта"
            delete_user_func = local_scope['delete_user']
            result = delete_user_func(user_identifier, config, node_ip, proto_port)
            
            "Если async"
            if hasattr(result, '__await__'):
                import asyncio
                result = await result
            
            log_event(f"Hot-reload DELETE успешно выполнен для пользователя {user_identifier}", level='INFO')
            return True, "Hot-reload удаление успешно"
            
        except ImportError as e:
            error_msg = f"Библиотека {lib_name} не найдена: {e}"
            log_event(error_msg, level='CRITICAL')
            return False, error_msg
            
        except Exception as e:
            error_msg = f"Ошибка выполнения delete_user скрипта: {e}"
            log_event(error_msg, level='CRITICAL')
            return False, error_msg


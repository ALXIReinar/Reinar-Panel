import ast
import asyncio
import hashlib
import importlib
import json
import math
import re
import traceback
from collections import defaultdict
from functools import lru_cache
from typing import Literal, Callable, Any

import flatten_json
import jmespath
import orjson

from node_client.api.sandbox.ast_validator import SecurityError, CodeSandboxValidator
from node_client.config import env
from node_client.logger_config import log_event

# Принудительная очистка кэша - для библиотек из шаблонов-скриптов
importlib.invalidate_caches()

class HotReloadExecutor:
    """Выполнение Python скриптов для hot-reload операций"""
    allowed_packages = {
        "json",
        "asyncio",
        "orjson",
        "re",
        "math",
        "jmespath",
        "flatten_json",
    }

    base_globals = {
        # Доступные модули по умолчанию
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
        "isinstance": isinstance, "all": all, "any": any, "bool": bool,
        "bytes": bytes, "bytearray": bytearray,
        "Exception": Exception, "ValueError": ValueError, "KeyError": KeyError,
        "NameError": NameError, "TypeError": TypeError, "AttributeError": AttributeError,
        "__name__": "__main__",  # Безопасный dunder атрибут
        "__doc__": None,  # Безопасный dunder атрибут
    }

    validator = CodeSandboxValidator()

    @classmethod
    def _prepare_globals(cls, lib_names: str | None = None) -> dict[str, Any]:
        """Формирует изолированный global_scope для конкретного запуска"""

        if lib_names is None:
            lib_names = []
        else:
            lib_names = lib_names.split(',')

        # Shallow copy словарь — это предотвратит кашу при замусоривании скоупа скриптом
        g_scope = cls.base_globals.copy()
        g_scope["__builtins__"] = cls.safe_builtins.copy()
        # Подменяем __import__ на нашу защиту
        inner_allowed_packages = cls.allowed_packages.copy()

        "Добавляем в g_scope, чтобы были доступны без импорта"
        for lib in lib_names:
            lib_clean = lib.strip()
            if lib_clean:
                g_scope[lib_clean] = importlib.import_module(lib_clean)
                # Добавляем полный путь модуля
                inner_allowed_packages.add(lib_clean)
                # Также добавляем корневой пакет (для поддержки from X.Y.Z import ...)
                root_package = lib_clean.split('.')[0]
                inner_allowed_packages.add(root_package)

        "Применяем упрощённый импорт в конце, чтобы все нужные либы были доступны ч/з import"
        g_scope['__builtins__']['__import__'] = cls._create_restricted_import(inner_allowed_packages)
        return g_scope

    @classmethod
    async def execute_action_script(
            cls,
            script: str,
            lib_names: str | None,
            node_ip: str,
            core_api_port: int,
            action: Literal["user_core_operation", "get_metrics"],
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
            "Пытаемся получить уже готовый байт код"
            compiled_code = cls._get_compiled_code(script)

            "Создаём окружение для выполнения скрипта"
            # ВАЖНО: передаём global_scope и как globals, и как locals
            # Это позволяет import работать корректно: импорты попадают в тот же scope
            # что и определения функций, и функции могут их видеть
            global_scope = cls._prepare_globals(lib_names)

            # Выполняем скрипт - импорты и функции попадут в global_scope
            exec(compiled_code, global_scope, global_scope)

            "Вызываем функцию из скрипта"
            action_user_func = (
                    global_scope.get('bulk_delete_users') or
                    global_scope.get('bulk_add_users') or
                    global_scope.get('get_metrics') or
                    global_scope.get('parse')
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

        except SecurityError as e:
            log_event(f"ПОПЫТКА ОБХОДА ПЕСОЧНИЦЫ: {str(e)}", level='CRITICAL')
            return False, f"Ошибка безопасности скрипта: {str(e)}"

        except ImportError as e:
            error_msg = str(e)
            log_event(f"\033[31mОШИБКА ИМПОРТА БИБЛИОТЕКИ\033[0m\nБиблиотека: {lib_names}\nAction: {action}\nДетали: {repr(e)}", level='CRITICAL')
            
            # Если это ошибка от restricted_import - возвращаем оригинальное сообщение
            if "запрещен в песочнице" in error_msg:
                return False, error_msg
            
            # Иначе стандартное сообщение
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


    @staticmethod
    def _create_restricted_import(allowed_libs: set[str]):
        """
        Создает безопасную функцию __import__, разрешающую импорт только из allowed_libs.
        
        Поддерживает:
        - import module
        - from module import attr
        - from module.submodule import attr as alias
        """

        def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
            # Получаем корневое имя пакета (например, 'cryptography' из 'cryptography.hazmat.primitives')
            root_package = name.split('.')[0]

            if root_package not in allowed_libs:
                raise ImportError(f"Импорт модуля '{name}' запрещен в песочнице.")

            # Выполняем импорт через встроенный __import__
            module = __import__(name, globals, locals, fromlist, level)
            
            # ВАЖНО: если fromlist не пустой (т.е. это from X import Y),
            # __import__ возвращает самый глубокий модуль, а не корневой
            # Например:
            # - import json → возвращает json
            # - from json import dumps → возвращает json (с атрибутом dumps)
            # - from json.encoder import JSONEncoder → возвращает json.encoder
            
            return module

        return restricted_import

    @classmethod
    @lru_cache(maxsize=env.lru_cache_max_size)
    def _compile_script_cached(cls, script_hash: str, script_code: str):
        """
        с LRU-кэшем.
        Аргумент script_hash нужен как хэшируемый ключ для lru_cache.

        Выполняется ТОЛЬКО ПРИ ПЕРВОМ ВЫЗОВЕ для каждого нового скрипта.
        При повторных вызовах возвращает скомпилированный Code Object из RAM.
        """
        # 1. Парсинг в AST
        parsed_ast = ast.parse(script_code)

        # 2. Проверка безопасности (AST-валидатор из прошлого ответа)
        cls.validator.visit(parsed_ast)

        # 3. Компиляция в RAM (файл на диск НЕ пишется!)
        compiled_code = compile(parsed_ast, filename="<db_template>", mode="exec")

        return compiled_code

    @classmethod
    def _get_compiled_code(cls, script_code: str):
        """Публичный интерфейс для получения скомпилированного кода"""
        # Хэшируем текст скрипта для эффективного поиска в кэше
        script_hash = hashlib.sha256(script_code.encode("utf-8")).hexdigest()

        # Возвращает результат из кэша (если уже вызывался)
        return cls._compile_script_cached(script_hash, script_code)

    @classmethod
    def get_compiled_func(cls, func_script: str, func_name: str, libs: str | None = None) -> Callable:
        # Используем global_scope как для globals так и для locals
        # чтобы импорты были доступны внутри функций
        global_scope = cls._prepare_globals(libs)

        compiled_code = cls._get_compiled_code(func_script)

        exec(compiled_code, global_scope, global_scope)

        "Достаём рабочую функцию"
        compiled_func = global_scope.get(func_name)
        if not compiled_func:
            msg = f"Функция не найдена в скрипте | func_name: \033[33m{func_name}\033[0m; \033[36m{func_script[:150]}\033[0m"
            log_event(msg, level='ERROR')
            raise ValueError(msg)

        return compiled_func
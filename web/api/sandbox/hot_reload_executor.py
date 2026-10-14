import ast  # noqa: I001
import asyncio
import hashlib
import importlib
import json
import math
import re
from collections import defaultdict
from functools import lru_cache
from typing import Callable, Any

import flatten_json
import jmespath
import orjson

from web.api.sandbox.ast_validator import SecurityError, CodeSandboxValidator
from web.config_dir.config import env
from web.utils.logger_config import log_event

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
        "int": int,
        "str": str,
        "float": float,
        "list": list,
        "dict": dict,
        "set": set,
        "len": len,
        "range": range,
        "round": round,
        "print": print,
        "enumerate": enumerate,
        "zip": zip,
        "map": map,
        "filter": filter,
        "isinstance": isinstance,
        "all": all,
        "any": any,
        "bool": bool,
        "bytes": bytes,
        "bytearray": bytearray,
        "Exception": Exception,
        "ValueError": ValueError,
        "KeyError": KeyError,
        "NameError": NameError,
        "TypeError": TypeError,
        "AttributeError": AttributeError,
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

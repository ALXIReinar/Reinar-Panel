import ast
import asyncio
import importlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Callable
from typing import Any

import flatten_json
import jmespath
import orjson

from node_client.api.sandbox.ast_validator import CodeSandboxValidator

# Принудительная очистка кэша - для библиотек из шаблонов-скриптов
importlib.invalidate_caches()


class TemplateCompiler:
    """Компиляция функций шаблона в изолированном окружении."""

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

    @staticmethod
    def _template_module(module):
        return module

    @classmethod
    def _prepare_globals(cls, lib_names: str | None = None) -> dict[str, Any]:
        """Формирует изолированный global_scope для конкретного запуска"""

        libraries = lib_names.split(',') if lib_names is not None else []

        # Shallow copy словарь — это предотвратит кашу при замусоривании скоупа скриптом
        g_scope = cls.base_globals.copy()
        g_scope["__builtins__"] = cls.safe_builtins.copy()
        # Подменяем __import__ на нашу защиту
        inner_allowed_packages = cls.allowed_packages.copy()

        "Добавляем в g_scope, чтобы были доступны без импорта"
        for lib in libraries:
            lib_clean = lib.strip()
            if lib_clean:
                g_scope[lib_clean] = cls._template_module(importlib.import_module(lib_clean))
                # Добавляем полный путь модуля
                inner_allowed_packages.add(lib_clean)
                # Также добавляем корневой пакет (для поддержки from X.Y.Z import ...)
                root_package = lib_clean.split('.')[0]
                inner_allowed_packages.add(root_package)

        "Применяем упрощённый импорт в конце, чтобы все нужные либы были доступны ч/з import"
        g_scope['__builtins__']['__import__'] = cls._create_restricted_import(inner_allowed_packages)
        return g_scope

    @classmethod
    def _create_restricted_import(cls, allowed_libs: set[str]):
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
            return cls._template_module(module)

        return restricted_import

    @classmethod
    def _get_compiled_code(cls, script_code: str):
        parsed_ast = ast.parse(script_code)
        cls.validator.visit(parsed_ast)
        return compile(parsed_ast, filename="<db_template>", mode="exec")

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
            raise ValueError(f"Функция не найдена в скрипте: {func_name}")

        return compiled_func

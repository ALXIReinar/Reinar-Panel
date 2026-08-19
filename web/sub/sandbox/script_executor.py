import ast
import asyncio
import hashlib
import importlib
import json
import math
import traceback
from collections import defaultdict
import re
from functools import lru_cache
from typing import Any

import flatten_json
import jmespath
import orjson

from web.sub.config_dir.config import env
from web.sub.config_dir.logger_config import log_event
from web.sub.sandbox.ast_validator import SecurityError, CodeSandboxValidator


class ScriptExecutor:
    validator = CodeSandboxValidator()

    @classmethod
    async def executing_link_processing(
            cls,
            sub_prepare_script: str,
            required_libs: str | None,
            user_obj: dict,
            config_link: str
    ):
        # 1. Формируем список БАЗОВЫХ разрешенных пакетов
        allowed_packages = {
            "json", "asyncio", "orjson", "re", "math",
            "defaultdict", "jmespath", "flatten_json"
        }

        # Добавляем пакеты из параметров функции
        if required_libs:
            for lib in required_libs.split(','):
                clean_lib = lib.strip().split('.')[0]
                if clean_lib:
                    allowed_packages.add(clean_lib)

        # 2. ЖЕСТКО ОЧИЩЕННЫЕ Builtins
        # ВАЖНО: Удалены type, dir, vars, eval, exec, globals, locals!
        safe_builtins = {
            "int": int, "str": str, "float": float, "list": list, "dict": dict,
            "set": set, "len": len, "range": range, "round": round, "print": print,
            "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
            "isinstance": isinstance, "all": all, "any": any, "bool": bool,
            "bytes": bytes, "bytearray": bytearray,
            "Exception": Exception, "ValueError": ValueError, "KeyError": KeyError,
            "NameError": NameError, "TypeError": TypeError, "AttributeError": AttributeError,

            # Подменяем __import__ на нашу защиту
            "__import__": cls._create_restricted_import(allowed_packages),
        }

        try:
            # 3. АНАЛИЗ И КОМПИЛЯЦИЯ (Безопасность на уровне AST)
            compiled_code = cls._get_compiled_code(sub_prepare_script)

            # 4. Формируем изолированный global_scope
            global_scope = {
                "__builtins__": safe_builtins,
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
            local_scope = {}

            # 5. ВЫПОЛНЕНИЕ СКОМПИЛИРОВАННОГО КОДА
            exec(compiled_code, global_scope, local_scope)

            parse_func = local_scope.get("prepare_sub")
            if not parse_func or not callable(parse_func):
                return False, 500, "Функция 'prepare_sub' не найдена в скрипте."

            result = parse_func(user_obj, config_link)

            if asyncio.iscoroutine(result):
                result = await result

            return True, result

        except SecurityError as e:
            log_event(f"ПОПЫТКА ОБХОДА ПЕСОЧНИЦЫ: {str(e)}", level='CRITICAL')
            return False, 403, f"Ошибка безопасности скрипта: {str(e)}"

        except SyntaxError as e:
            return False, 400, f"Синтаксическая ошибка: {e.msg} (строка {e.lineno})"

        except Exception as e:
            return False, 500, f"Ошибка выполнения ({type(e).__name__}): {str(e)}"

    @staticmethod
    def _create_restricted_import(allowed_libs: set[str]):
        """Создает безопасную функцию __import__, разрешающую импорт только из allowed_libs"""

        def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
            # Получаем корневое имя пакета (например, 'cryptography' из 'cryptography.hazmat.primitives')
            root_package = name.split('.')[0]

            if root_package not in allowed_libs:
                raise ImportError(f"Импорт модуля '{name}' запрещен в песочнице.")

            return __import__(name, globals, locals, fromlist, level)

        return restricted_import


    def _validate_and_compile_script(self, script_code: str):
        """
        1. Парсит код в AST.
        2. Проверяет на опасные вызовы (интроспекцию).
        3. Компилирует код в байткод.
        """
        try:
            parsed_ast = ast.parse(script_code)
        except SyntaxError as e:
            raise e

        # Запускаем валидатор безопасности
        self.validator.visit(parsed_ast)

        # Если проверка прошла успешно — компилируем в байткод
        return compile(parsed_ast, filename="<db_template>", mode="exec")


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
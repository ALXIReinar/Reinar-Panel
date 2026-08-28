import ast
import asyncio
import hashlib
import importlib
from collections import defaultdict
from functools import lru_cache

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
            config_link: dict,
    ):
        # 1. Формируем список БАЗОВЫХ разрешенных пакетов
        allowed_packages = {
            "json", "asyncio", "orjson", "re", "math",
            "jmespath", "flatten_json"
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
            "__name__": "__main__",  # Безопасный dunder атрибут
            "__doc__": None,  # Безопасный dunder атрибут

            # Подменяем __import__ на нашу защиту
            "__import__": cls._create_restricted_import(allowed_packages),
        }

        try:
            # 3. АНАЛИЗ И КОМПИЛЯЦИЯ (Безопасность на уровне AST)
            compiled_code = cls._get_compiled_code(sub_prepare_script)

            imported_allowed_packages = {allow_pckg.strip(): importlib.import_module(allow_pckg.strip()) for allow_pckg in allowed_packages}

            # 4. Формируем изолированный global_scope
            global_scope = {
                "__builtins__": safe_builtins,
                # Доступные модули по умолчанию
                **imported_allowed_packages,
                "defaultdict": defaultdict,
            }

            # 5. ВЫПОЛНЕНИЕ СКОМПИЛИРОВАННОГО КОДА
            exec(compiled_code, global_scope, global_scope)

            parse_func = global_scope.get("prepare_sub")
            if not parse_func:
                return False, "Функция 'prepare_sub' не найдена в скрипте."

            result = parse_func(user_obj, config_link['conf_url'], config_link['n_address'], config_link['n_title'])

            if asyncio.iscoroutine(result):
                result = await result

            return True, result

        except SecurityError as e:
            log_event(f"ПОПЫТКА ОБХОДА ПЕСОЧНИЦЫ: {str(e)}", level='CRITICAL')
            return False, f"Ошибка безопасности скрипта: {str(e)}"

        except ImportError as e:
            error_msg = str(e)
            log_event(f"\033[31mОШИБКА ИМПОРТА БИБЛИОТЕКИ\033[0m\nБиблиотека: {required_libs}\nAction: prepare_sub\nДетали: {repr(e)}", level='CRITICAL')

            # Если это ошибка от restricted_import - возвращаем оригинальное сообщение
            if "запрещен в песочнице" in error_msg:
                return False, error_msg

            # Иначе стандартное сообщение
            return False, f"Библиотека {required_libs} не найдена. Убедитесь что она установлена в виртуальном окружении."

        except SyntaxError as e:
            return False, f"Синтаксическая ошибка: {e.msg} (строка {e.lineno})"

        except Exception as e:
            return False, f"Ошибка выполнения ({type(e).__name__}): {str(e)}"

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
import asyncio
import hashlib
import traceback
from functools import lru_cache
from typing import Literal

from node_client.api.sandbox.ast_validator import SecurityError
from node_client.api.sandbox.compiler import TemplateCompiler
from node_client.api.sandbox.core_api import call_core_api, template_module
from node_client.config import env
from node_client.utils.logger_config import log_event


class HotReloadExecutor(TemplateCompiler):
    """Выполнение скриптов шаблона с кешем байт-кода нод-клиента."""

    _template_module = staticmethod(template_module)

    @classmethod
    @lru_cache(maxsize=env.lru_cache_max_size)
    def _compile_script_cached(cls, script_hash: str, script_code: str):
        return super()._get_compiled_code(script_code)

    @classmethod
    def _get_compiled_code(cls, script_code: str):
        script_hash = hashlib.sha256(script_code.encode("utf-8")).hexdigest()
        return cls._compile_script_cached(script_hash, script_code)

    @classmethod
    async def execute_action_script(
        cls,
        script: str,
        lib_names: str | None,
        node_ip: str,
        core_api_port: int,
        action: Literal["user_core_operation", "get_metrics", "parse_metrics"],
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
                global_scope.get('bulk_delete_users')
                or global_scope.get('bulk_add_users')
                or global_scope.get('get_metrics')
                or global_scope.get('parse_metrics')
            )
            if not action_user_func:
                msg = (
                    "Ни одна из функций: (bulk_delete_users, bulk_add_users, get_metrics, parse) - не найдена в скрипте"
                )
                log_event(msg, level='ERROR')
                return False, msg

            "Подбираем набор аргументов исходя от действия скрипта"
            args_func_map = {
                "user_core_operation": (
                    user_obj,
                    node_ip,
                    core_api_port,
                    custom_params,
                ),  # Подходит для бульк/обычных вставок/удалений
                "get_metrics": (node_ip, core_api_port, custom_params),
                "parse_metrics": (
                    custom_params.get('raw_metrics'),
                    custom_params.get('vpn_users'),
                    custom_params.get('local_state'),
                ),
            }
            if action != "parse_metrics":
                result = await call_core_api(action_user_func, *args_func_map[action])
            else:
                result = action_user_func(*args_func_map[action])
                if asyncio.iscoroutine(result):
                    result = await result

            log_event(f"Hot-reload успешно выполнен для пользователя | user_obj: \033[37m{user_obj}\033[0m")
            return True, result

        except SecurityError as e:
            log_event(f"ПОПЫТКА ОБХОДА ПЕСОЧНИЦЫ: {str(e)}", level='CRITICAL')
            return False, f"Ошибка безопасности скрипта: {str(e)}"

        except ImportError as e:
            error_msg = str(e)
            log_event(
                f"\033[31mОШИБКА ИМПОРТА БИБЛИОТЕКИ\033[0m\nБиблиотека: {lib_names}\nAction: {action}\nДетали: {repr(e)}",
                level='CRITICAL',
            )
            # Если это ошибка от restricted_import - возвращаем оригинальное сообщение
            if "запрещен в песочнице" in error_msg:
                return False, error_msg
            # Иначе стандартное сообщение
            return False, f"Библиотека {lib_names} не найдена. Убедитесь что она установлена в виртуальном окружении."
        except SyntaxError as e:
            script_lines = script.split('\n')
            error_line = script_lines[e.lineno - 1] if e.lineno and e.lineno <= len(script_lines) else "???"

            log_event(
                f"\033[31mСИНТАКСИЧЕСКАЯ ОШИБКА В СКРИПТЕ\033[0m\nAction: {action}\nСтрока {e.lineno}: {error_line}\nОшибка: {e.msg}\nПозиция: {' ' * (e.offset - 1) if e.offset else ''}^\n",
                level='CRITICAL',
            )

            return False, f"Синтаксическая ошибка в скрипте: {e.msg} (строка {e.lineno})"
        except Exception as e:
            tb_str = traceback.format_exc()

            log_event(
                f"\033[31mОШИБКА ВЫПОЛНЕНИЯ СКРИПТА\033[0m\nAction: {action}\nБиблиотеки: {lib_names}\nТип ошибки: {type(e).__name__}\nСообщение: {str(e)}\n\nTraceback:\n{tb_str}\n",
                level='CRITICAL',
            )
            return False, f"Ошибка выполнения скрипта ({type(e).__name__}): {str(e)}"

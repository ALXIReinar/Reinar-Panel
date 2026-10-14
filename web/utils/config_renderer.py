import orjson
from flatten_json import flatten
from jinja2 import Template

from web.api.sandbox.hot_reload_executor import HotReloadExecutor


def generate_config_link_from_raw_content(
    raw_config_content: str,
    url_template: str,
    config2json_script: str | None = None,
    conf_converter_libs: str | None = None,
) -> str:
    """Генерирует config_link из сырого содержимого конфиг-файла"""

    # 1. Конвертируем raw content в JSON dict
    if config2json_script is None:
        # Если скрипт не указан - это уже JSON
        config_dict = orjson.loads(raw_config_content)
    else:
        # Используем кастомный конвертер из шаблона
        config2json_func = HotReloadExecutor.get_compiled_func(config2json_script, 'config2json', conf_converter_libs)
        config_dict = config2json_func(raw_config_content)

    # 2. Делаем все ключи плоскими (nested.key.path -> nested___key___path)
    flat_config = flatten(config_dict, separator='___')

    template = Template(url_template)
    config_link = template.render(flat_config)
    return config_link

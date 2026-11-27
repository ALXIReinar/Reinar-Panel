import json
import re
import time
from pathlib import Path

from node_client.api.sandbox import TemplateCompiler

from .db import Row


class NodeConfig:
    def __init__(self, node: Row, template: Row):
        self.path = Path(node["config_path"])
        script = template["config2json_script"]
        self.convert = (
            json.loads
            if script is None
            else TemplateCompiler.get_compiled_func(script, "config2json", template["conf_converter_libs"])
        )

    def read(self) -> dict:
        text = self.path.read_text(encoding="utf-8")
        data = self.convert(text)
        if not isinstance(data, dict):
            raise ValueError("Конвертер конфига должен вернуть JSON-объект")
        return data

    def wait_user(self, subscription: Row, present: bool, timeout: int) -> tuple[dict | None, float]:
        started = time.monotonic()
        user_uuid = str(subscription["uuid"])
        # Короткий ID подписки может случайно встретиться внутри ключа или short ID ядра.
        user_id = re.compile(rf"(?<![A-Za-z0-9]){re.escape(str(subscription['id']))}(?![A-Za-z0-9])")
        while True:
            try:
                data = self.read()
            except (OSError, ValueError):
                data = None
            elapsed = time.monotonic() - started
            if data is not None:
                found = any(
                    isinstance(value, str) and (user_uuid in value or user_id.search(value)) for value in leaves(data)
                )
                if found == present:
                    return data, elapsed
            if elapsed >= timeout:
                return None, elapsed
            time.sleep(min(1, timeout - elapsed))


def leaves(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from leaves(child)
    elif isinstance(value, list):
        for child in value:
            yield from leaves(child)
    else:
        yield value

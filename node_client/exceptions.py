class NodeInitError(Exception):
    """Ошибка валидации или компиляции параметров виртуальной ноды при регистрации."""

    def __init__(self, node_proto_id: int, field: str, reason: str):
        self.node_proto_id = node_proto_id
        self.field = field
        self.reason = reason
        super().__init__(f"Ошибка инициализации виртуальной ноды {node_proto_id} (поле: '{field}'): {reason}")


class NodeNotRegisteredError(Exception):
    """Исключение при обращении к незарегистрированной виртуальной ноде."""

    def __init__(self, node_proto_id: int):
        self.node_proto_id = node_proto_id
        super().__init__(f"Виртуальная нода {node_proto_id} не зарегистрирована в нод-клиенте")

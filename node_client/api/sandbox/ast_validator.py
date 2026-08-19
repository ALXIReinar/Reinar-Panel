import ast


class SecurityError(Exception):
    """Исключение при попытке обхода песочницы"""
    pass


class CodeSandboxValidator(ast.NodeVisitor):
    """
    AST-анализатор, проверяющий код на опасные конструкции
    до его передачи в exec().
    """
    # Запрещенные имена атрибутов, используемые для интроспекции и обхода
    FORBIDDEN_ATTRS = {
        "__subclasses__",
        "__bases__",
        "__mro__",
        "__class__",
        "__globals__",
        "__code__",
        "__closure__",
        "__dict__",
    }

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr in self.FORBIDDEN_ATTRS:
            raise SecurityError(
                f"Использование атрибута '{node.attr}' запрещено в целях безопасности."
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        # Запрещаем прямое обращение к внутренним встроенным переменным
        if node.id.startswith("__") and node.id.endswith("__"):
            if node.id not in ("__name__", "__doc__"):
                raise SecurityError(f"Обращение к системному имени '{node.id}' запрещено.")
        self.generic_visit(node)

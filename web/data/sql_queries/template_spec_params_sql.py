from asyncpg import Connection, ForeignKeyViolationError


class TemplateSpecParamsQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def bulk_add(self, tmp_id: int, keys: list[str]) -> tuple[int, str, int]:
        """
        Bulk добавление spec параметров к шаблону
        
        Returns:
            tuple[status_code, message, added_count]
            - 200, 'Параметры добавлены', count - успех
            - 404, 'Шаблон не найден', 0 - шаблон не существует
        """
        if not keys:
            return 200, 'Нет параметров для добавления', 0

        # Проверяем существование шаблона
        check_query = "SELECT id FROM proto_templates WHERE id = $1"
        template_exists = await self.conn.fetchrow(check_query, tmp_id)
        
        if not template_exists:
            return 404, 'Шаблон не найден', 0

        query = """
        INSERT INTO template_spec_params (tmp_id, key)
        SELECT $1, unnest($2::text[])
        ON CONFLICT (tmp_id, key) DO NOTHING
        RETURNING id
        """
        
        result = await self.conn.fetch(query, tmp_id, keys)
        added_count = len(result)
        
        return 200, f'Добавлено параметров: {added_count}', added_count

    async def bulk_delete(self, param_ids: list[int]) -> tuple[int, str, int]:
        """
        Bulk удаление spec параметров
        
        Returns:
            tuple[status_code, message, deleted_count]
            - 200, 'Параметры удалены', count - успех
        """

        query = "DELETE FROM template_spec_params WHERE id = ANY($1) RETURNING id"
        try:
            result = await self.conn.fetch(query, param_ids)
            deleted_count = len(result)
            return 200, f'Удалено параметров: {deleted_count}', deleted_count
        except ForeignKeyViolationError:
            "RESTRICT Constraint"
            return 409, 'Эти параметры используются какими-то из виртуальных нод', 0

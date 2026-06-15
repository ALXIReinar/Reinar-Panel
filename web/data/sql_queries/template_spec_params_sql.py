from asyncpg import Connection, ForeignKeyViolationError, UniqueViolationError


class TemplateSpecParamsQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def bulk_add(self, tmp_id: int, keys: list[str]):
        """
        Как будто хочется CTE для 404?

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
        return 200, f'Добавлено параметров: {len(result)}', [rec['id'] for rec in result]

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


    async def values_bulk_add(self, node_proto_id: int, spec_param_values: dict):
        query = """
        INSERT INTO nodes_protocoles_spec_params_values (node_proto_id, spec_key_id, value) 
        SELECT $1, t.spec_key_id, t.value FROM UNNEST ($2::integer[], $3::text[]) AS t(spec_key_id, value)
        RETURNING id
        """
        try:
            # Пользуемся фишкой структуры в Pydantic схеме: spec_param_values: {"spec_key_id": "static_value"}
            spec_key_ids, spec_values = list(spec_param_values.keys()), list(spec_param_values.values())

            spec_value_ids = await self.conn.fetch(query, node_proto_id, spec_key_ids, spec_values)
            return 200, 'Значения указаны под выбранные ключи и эту виртуальную ноду', [rec['id'] for rec in spec_value_ids]

        except UniqueViolationError:
            return 409, 'Все ключи должны быть выбраны только один раз', None


    async def values_bulk_delete(self, value_ids: list[int]):
        query = 'DELETE FROM nodes_protocoles_spec_params_values WHERE id = ANY($1) RETURNING id'
        return await self.conn.fetch(query, value_ids)
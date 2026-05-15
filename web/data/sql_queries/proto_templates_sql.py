from asyncpg import Connection, UniqueViolationError
from asyncpg.exceptions import ForeignKeyViolationError


class ProtoTemplatesQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def get_all(self, last_id: int | None, sort_by: str, limit: int):
        """Получить список всех шаблонов с пагинацией"""
        cursor_condition = 'WHERE id < $2'
        if sort_by == 'asc':
            cursor_condition = 'WHERE id > $2'

        if last_id is None:
            cursor_condition = ''

        query = f"""
        SELECT id, title, url_tmp, status, separator
        FROM proto_templates
        {cursor_condition}
        ORDER BY id {sort_by}
        LIMIT $1
        """

        if last_id is None:
            return await self.conn.fetch(query, limit)

        return await self.conn.fetch(query, limit, last_id)


    async def get_by_id(self, tmp_id: int, spec_only: bool):
        """Получить шаблон по ID с привязанными spec параметрами"""
        template_query = "SELECT id, title, url_tmp, status, separator FROM proto_templates WHERE id = $1"
        spec_params_query = "SELECT id, key FROM template_spec_params WHERE tmp_id = $1"

        "Облегчённый вариант(если в LocalStorage есть template)"
        if spec_only:
            spec_params = await self.conn.fetchrow(template_query, tmp_id)
            return {'spec_params': spec_params}

        template = await self.conn.fetchrow(template_query, tmp_id)
        if not template:
            return None

        spec_params = await self.conn.fetch(spec_params_query, tmp_id)
        return {'template': template, 'spec_params': spec_params}


    async def create(self, title: str) -> tuple[int, str, int | None]:
        """
        Создать новый шаблон
        
        Returns:
            tuple[status_code, message, template_id]
            - 201, 'Шаблон создан', template_id - успех
            - 409, 'Шаблон с таким названием уже существует', None - конфликт
        """
        query = "INSERT INTO proto_templates (title) VALUES ($1) RETURNING id"

        try:
            tmp_id = await self.conn.fetchval(query, title)
            return 201, 'Шаблон создан', tmp_id

        except UniqueViolationError:
            return 409, 'Шаблон с таким названием уже существует', None


    async def update(self, tmp_id: int, url_tmp: str | None = None, separator: str | None = None) -> tuple[int, str]:
        """
        Обновить шаблон
        
        Returns:
            tuple[status_code, message]
            - 200, 'Шаблон обновлён' - успех
            - 404, 'Шаблон не найден' - не существует
        """
        updates = []
        params = []
        param_idx = 1

        if url_tmp is not None:
            updates.append(f"url_tmp = ${param_idx}")
            params.append(url_tmp)
            param_idx += 1

        if separator is not None:
            updates.append(f"separator = ${param_idx}")
            params.append(separator)
            param_idx += 1

        if not updates:
            return 200, 'Нет полей для обновления'

        query = f"""
        UPDATE proto_templates SET {', '.join(updates)}
        WHERE id = ${param_idx}
        RETURNING id
        """
        params.append(tmp_id)

        result = await self.conn.fetchrow(query, *params)
        if not result:
            return 404, 'Шаблон не найден'

        return 200, 'Шаблон обновлён'


    async def delete(self, tmp_id: int) -> tuple[int, str]:
        """
        Удалить шаблон
        
        Returns:
            tuple[status_code, message]
            - 200, 'Шаблон удалён' - успех
            - 404, 'Шаблон не найден' - не существует
            - 409, 'Невозможно удалить: шаблон используется' - RESTRICT
        """
        query = "DELETE FROM proto_templates WHERE id = $1 RETURNING id"

        try:
            result = await self.conn.fetchval(query, tmp_id)
            if not result:
                return 404, 'Шаблон не найден'

            return 200, 'Шаблон удалён'

        except ForeignKeyViolationError:
            "RESTRICT на удаление шаблона, если есть ссылающиеся записи"
            return 409, 'Невозможно удалить: шаблон используется виртуальными нодами или spec параметрами'

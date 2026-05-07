from asyncpg import ForeignKeyViolationError, Connection

from web.utils.logger_config import log_event


class ProtocolCommandsQueries:
    """Запросы для работы с командами протоколов"""

    def __init__(self, conn: Connection):
        self.conn = conn

    async def get_command(self, cmd_id: int):
        """Получить команду по ID"""
        query = "SELECT id, proto_id, cmd_title, command, created_at FROM protocols_commands WHERE id = $1"
        return await self.conn.fetchrow(query, cmd_id)


    async def get_protocol_commands(self, proto_id: int):
        """Получить все команды протокола"""
        query = "SELECT id, cmd_title, command, created_at FROM protocols_commands WHERE proto_id = $1"
        return await self.conn.fetch(query, proto_id)


    async def insert_commands_bulk(self, proto_id: int, commands: list[dict]) -> tuple[int, list]:
        """Массовая вставка команд для протокола

        Args:
            proto_id: ID протокола
            commands: [{"cmd_title": "add_user", "command": "xray add ..."}, ...]

        Returns:
            list[id1, id2] вставленных команд
        """
        if not commands:
            return 200, []

        try:
            "Вставка"
            query = """
            INSERT INTO protocols_commands (proto_id, cmd_title, command)
            SELECT $1, cmd_titles, cmds
            FROM UNNEST($2::text[], $3::text[]) AS t(cmd_titles, cmds)
            RETURNING id
            """
            cmd_titles, cmds = zip(*(cmd.values() for cmd in commands))
            res = await self.conn.fetch(query, proto_id, cmd_titles, cmds)
            return 200, res

        except ForeignKeyViolationError:
            "Протокола не существует"
            log_event(f'Протокола не существует | proto_id:033[31m{proto_id}\033[0m', level='WARNING')
            return 404, []


    async def update_commands_bulk(self, commands: list[dict]) -> list[dict]:
        """Массовое обновление команд"""
        if not commands:
            return []

        query = """
        UPDATE protocols_commands AS pc
        SET cmd_title = t.cmd_titles,
            command   = t.cmds
        FROM UNNEST($1::bigint[], $2::text[], $3::text[]) AS t(ids, cmd_titles, cmds)
        WHERE pc.id = t.ids
        RETURNING id
        """
        ids, cmd_titles, cmds = zip(*(cmd.values() for cmd in commands))
        res = await self.conn.fetch(query, ids, cmd_titles, cmds)
        return res


    async def delete_commands_bulk(self, cmd_ids: list[int]) -> int:
        """Массовое удаление команд"""
        if not cmd_ids:
            return 0

        query = "DELETE FROM protocols_commands WHERE id = ANY($1)"
        res = await self.conn.execute(query, cmd_ids)
        return int(res.split()[-1])

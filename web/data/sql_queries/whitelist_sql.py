from asyncpg import Connection


class WhitelistQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def get_all(self):
        query = 'SELECT command FROM whitelist_commands WHERE is_active = true'
        res = await self.conn.fetch(query)
        return res


    async def bulk_update(self, set_as_active: list[int], set_as_inactive: list[int]) -> tuple[int, int]:
        active_count, inactive_count = 0, 0

        "Активация"
        if set_as_active:
            query = 'UPDATE whitelist_commands SET is_active = true WHERE id = ANY($1) RETURNING id'
            result = await self.conn.fetch(query, set_as_active)
            active_count = len(result)

        "Деактивация"
        if set_as_inactive:
            query = 'UPDATE whitelist_commands SET is_active = false WHERE id = ANY($1) RETURNING id'
            result = await self.conn.execute(query,set_as_inactive)
            inactive_count = len(result)

        return active_count, inactive_count


    async def bulk_add(self, commands: list[str]):
        query = """
        INSERT INTO whitelist_commands (command) SELECT cmd FROM UNNEST($1::text[]) AS t(cmd)
        ON CONFLICT (command) DO NOTHING RETURNING id
        """
        res = await self.conn.fetch(query, commands)
        return res


    async def bulk_delete(self, ids: list[int]):
        query = "DELETE FROM whitelist_commands WHERE id = ANY($1)"
        res = await self.conn.fetch(query, ids)
        return res

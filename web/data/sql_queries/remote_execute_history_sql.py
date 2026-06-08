from asyncpg import Connection


class RemoteCommandHistoryQueries:
    def __init__(self, conn: Connection):
        self.conn = conn


    async def save_action(self, node_proto_id: int, private_ip: str, api_port: int, command: str) -> int:
        """
        Сохранить запись о начале выполнения команды
        
        Returns:
            action_id - ID созданной записи
        """
        query = """
        INSERT INTO remote_execute_history (node_proto_id, private_ip, api_port, command, status)
        VALUES ($1, $2, $3, $4, 1)
        RETURNING id
        """
        return await self.conn.fetchval(query, node_proto_id, private_ip, api_port, command)


    async def update_action(
        self,
        action_id: int,
        status: int,
        stdout: str | None = None,
        stderr: str | None = None,
        exit_code: int | None = None,
        status_code: int | None = None,
        node_success: bool | None = None,
        exception_text: str | None = None
    ):
        """Обновить запись о выполнении команды"""
        updates = ['status = $2', 'updated_at = NOW()']
        params = [action_id, status]
        param_idx = 3

        if stdout is not None:
            updates.append(f"stdout = ${param_idx}")
            params.append(stdout)
            param_idx += 1

        if stderr is not None:
            updates.append(f"stderr = ${param_idx}")
            params.append(stderr)
            param_idx += 1

        if exit_code is not None:
            updates.append(f"exit_code = ${param_idx}")
            params.append(exit_code)
            param_idx += 1

        if status_code is not None:
            updates.append(f"status_code = ${param_idx}")
            params.append(status_code)
            param_idx += 1

        if node_success is not None:
            updates.append(f"node_success = ${param_idx}")
            params.append(node_success)
            param_idx += 1

        if exception_text is not None:
            updates.append(f"exception_text = ${param_idx}")
            params.append(exception_text)
            param_idx += 1

        query = f"""
        UPDATE remote_execute_history
        SET {', '.join(updates)}
        WHERE id = $1
        """
        
        await self.conn.execute(query, *params)


    async def get_history_all(self, last_id: int | None, sort_by: str, limit: int):
        """Получить историю выполнения команд с пагинацией"""
        cursor_condition = 'WHERE id < $2'
        if sort_by == 'asc':
            cursor_condition = 'WHERE id > $2'

        if last_id is None:
            cursor_condition = ''

        query = f"""
        SELECT id, status, command, exit_code, node_proto_id, api_port, private_ip, created_at, status_code, node_success, updated_at
        FROM remote_execute_history
        {cursor_condition}
        ORDER BY id {sort_by}
        LIMIT $1
        """

        if last_id is None:
            return await self.conn.fetch(query, limit)

        return await self.conn.fetch(query, limit, last_id)

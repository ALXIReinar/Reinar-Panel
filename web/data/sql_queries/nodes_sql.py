from asyncpg import Connection, UniqueViolationError


class NodesQueries:
    """Запросы для работы с физическими нодами"""

    def __init__(self, conn: Connection):
        self.conn = conn

    async def create_node(
        self, ip: str, private_ip: str, api_port: int, node_name: str, title: str, is_active: bool = True
    ) -> int:
        """Создать физическую ноду"""
        query = """
        INSERT INTO nodes (ip, private_ip, api_port, node_name, title, is_active)
        VALUES ($1, $2, $3, $4, $5, $6) 
        ON CONFLICT DO NOTHING
        RETURNING id
        """  # noqa: W291
        return await self.conn.fetchval(query, ip, private_ip, api_port, node_name, title, is_active)

    async def get_node(self, node_id: int):
        """Получить ноду по ID"""
        query = """
        SELECT id AS node_id, ip, private_ip, api_port, title, is_active, created_at, updated_at FROM nodes WHERE id = $1
        """
        return await self.conn.fetchrow(query, node_id)

    async def get_all_nodes(self, is_active: bool | None, limit: int, offset: int):
        """Получить все ноды с опциональными фильтрами"""
        conditions, params = [], []
        param_count = 3

        if is_active is not None:
            conditions.append(f"n.is_active = ${param_count}")
            params.append(is_active)
            param_count += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
        SELECT n.id, n.ip, n.private_ip, n.api_port, n.title, n.created_at, n.updated_at, n.is_active, COUNT(np.id) AS binded_vnodes_count
        FROM nodes n
        LEFT JOIN nodes_protocols np ON n.id = np.node_id
        {where_clause}
        GROUP BY n.id, n.ip, n.private_ip, n.api_port, n.title, n.created_at, n.updated_at, n.is_active
        LIMIT $1 OFFSET $2
        """

        return await self.conn.fetch(query, limit, offset, *params)

    async def update_node(
        self,
        node_id: int,
        ip: str | None = None,
        private_ip: str | None = None,
        api_port: int | None = None,
        title: str | None = None,
        is_active: bool | None = None,
    ):
        """Обновить ноду"""
        updates = []
        params = []
        param_count = 1
        if ip is not None:
            updates.append(f"ip = ${param_count}")
            params.append(ip)
            param_count += 1
        if private_ip is not None:
            updates.append(f"private_ip = ${param_count}")
            params.append(private_ip)
            param_count += 1
        if api_port is not None:
            updates.append(f"api_port = ${param_count}")
            params.append(api_port)
            param_count += 1
        if title is not None:
            updates.append(f"title = ${param_count}")
            params.append(title)
            param_count += 1
        if is_active is not None:
            updates.append(f"is_active = ${param_count}")
            params.append(is_active)
            param_count += 1
        if not updates:
            return
        updates.append(f"updated_at = NOW()")  # noqa: F541
        params.append(node_id)
        query = f"""
        UPDATE nodes
        SET {', '.join(updates)}
        WHERE id = ${param_count}
        """
        try:
            await self.conn.execute(query, *params)
            return 200, 'Нода обновлена'
        except UniqueViolationError as e:
            return 409, {'message': 'Конфликт хост-порт пар', 'err_message': str(repr(e))}

    async def delete_node(self, node_id: int):
        """Удалить ноду"""
        query = "DELETE FROM nodes WHERE id = $1"
        await self.conn.execute(query, node_id)

    async def get_node_protocols(self, node_id: int, limit: int, offset: int):
        """Получить все виртуальные ноды на физической ноде"""
        query = """
        SELECT np.id as node_proto_id, np.tmp_id, np.sub_node_address, np.proto_port, np.metrics_port, np.user_visible, np.title
        FROM nodes_protocols np
        JOIN nodes n ON np.node_id = n.id
        WHERE np.node_id = $1
        LIMIT $2 OFFSET $3
        """
        return await self.conn.fetch(query, node_id, limit, offset)

    async def get_startup_data(self, node_title: str, node_proto_ids: list[int] | None = None) -> dict | None:
        """Получить служебные данные виртуальных нод физической ноды для инициализации нод-клиента."""
        # 1. Проверяем существование физической ноды
        node = await self.conn.fetchrow("SELECT id FROM nodes WHERE title = $1", node_title)
        if not node:
            return None

        # 2. Выбираем служебные данные зарегистрированных виртуальных нод
        query = """
        WITH pre_agg_user_injectors AS (
            SELECT tmp_id,
                   json_agg(
                       json_build_object(
                           'flatten_array_cursor', flatten_array_cursor,
                           'extractor_script', extractor_script,
                           'libs', libs
                       )
                       ORDER BY id  -- порядок инжекторов в ответе детерминирован
                   ) AS user_injectors
            FROM templates_users_extractors
            GROUP BY tmp_id
        )
        SELECT np.id                  AS node_proto_id,
               np.config_path         AS filepath,
               COALESCE(aui.user_injectors, '[]'::json) AS user_injectors,
               np.reload_core_command AS reload_command,
               pt.config2json_script,
               pt.json2config_script,
               pt.conf_converter_libs,
               pt.api_bulk_add_user_script,
               pt.api_bulk_delete_user_script,
               COALESCE(np.metrics_command, pt.metrics_command) AS metrics_command,
               pt.api_metrics_script,
               pt.proto_python_lib,  -- уже включает библиотеки парсера метрик (миграция b4e8a1c9d2f0)
               pt.metrics_parser_code
        FROM nodes_protocols np
        JOIN nodes n            ON n.id = np.node_id
        JOIN proto_templates pt ON pt.id = np.tmp_id
        LEFT JOIN pre_agg_user_injectors aui ON aui.tmp_id = pt.id
        WHERE n.title = $1
          AND np.reg_status = 2
          -- Без пути к конфигу ноду не обслужить: такая нода уходит в missing, а не роняет ответ всей физической ноде
          AND np.config_path IS NOT NULL
          AND ($2::int[] IS NULL OR cardinality($2::int[]) = 0 OR np.id = ANY($2::int[]))
        ORDER BY np.id ASC
        """
        filter_ids = node_proto_ids if node_proto_ids else None
        rows = await self.conn.fetch(query, node_title, filter_ids)

        found_ids = set(row["node_proto_id"] for row in rows)
        requested_ids = list(dict.fromkeys(node_proto_ids or []))
        missing = [nid for nid in requested_ids if nid not in found_ids]

        return {
            "node_title": node_title,
            "nodes": [dict(row) for row in rows],
            "missing": missing,
        }

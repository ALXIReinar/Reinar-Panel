from typing import Literal

from asyncpg import Connection, ForeignKeyViolationError, UniqueViolationError

from web.utils.anything import CoreProtoActions, VnodeRegStatuses


class NodesProtocolsQueries:
    """Запросы для работы с виртуальными нодами (протоколы на физических нодах)"""

    def __init__(self, conn: Connection):
        self.conn = conn

    async def get_node_protocol(self, np_id: int):
        """Получить виртуальную ноду по ID"""
        query = """
        SELECT
            np.node_id, np.proto_id, p.name as proto_name, n.ip, n.private_ip, n.api_port, np.sub_node_address, np.proto_port,
            np.metrics_port, n.is_active, np.user_visible, np.title, np.config_link, np.config_path, n.title as node_title,
            np.created_at, np.constant_node_data_obj, np.reload_core_command
        FROM nodes_protocols np
        JOIN nodes n ON np.node_id = n.id
        JOIN protocols p ON np.proto_id = p.id
        WHERE np.id = $1
        """
        return await self.conn.fetchrow(query, np_id)

    async def get_node_protocols(self, node_id: int, limit: int, offset: int):
        """Получить все виртуальные ноды на физической ноде"""
        query = """
        SELECT np.id as node_proto_id, np.proto_id, p.name as proto_name, np.sub_node_address, np.proto_port, np.metrics_port, np.user_visible, np.title
        FROM nodes_protocols np
        JOIN protocols p ON np.proto_id = p.id
        JOIN nodes n ON np.node_id = n.id
        WHERE np.node_id = $1
        LIMIT $2 OFFSET $3
        """
        return await self.conn.fetch(query, node_id, limit, offset)

    async def update_node_protocol(
        self,
        np_id: int,
        config_path: str | None = None,
        title: str | None = None,
        metrics_port: int | None = None,
        proto_port: int | None = None,
        sub_node_address: str | None = None,
        user_visible: bool | None = None,
        constant_node_data_obj: dict | None = None,
        reload_core_command: str | int | None = None,
    ) -> tuple[int, str]:
        """
        Универсальное обновление виртуальной ноды

        Returns:
            tuple[status_code, message]
            - 200, 'Нода обновлена' - успех
            - 409, 'Конфликт портов...' - нарушение уникального индекса
            - 404, 'Виртуальная нода не найдена' - нода не существует
        """
        updates = []
        params = []
        param_idx = 1

        if config_path is not None:
            updates.append(f"config_path = ${param_idx}")
            params.append(config_path)
            param_idx += 1

        if title is not None:
            updates.append(f"title = ${param_idx}")
            params.append(title)
            param_idx += 1

        if metrics_port is not None:
            updates.append(f"metrics_port = ${param_idx}")
            params.append(metrics_port)
            param_idx += 1

        if proto_port is not None:
            updates.append(f"proto_port = ${param_idx}")
            params.append(proto_port)
            param_idx += 1

        if sub_node_address is not None:
            updates.append(f"sub_node_address = ${param_idx}")
            params.append(sub_node_address)
            param_idx += 1

        if user_visible is not None:
            updates.append(f"user_visible = ${param_idx}")
            params.append(user_visible)
            param_idx += 1

        if constant_node_data_obj is not None:
            updates.append(f"constant_node_data_obj = ${param_idx}")
            params.append(constant_node_data_obj)
            param_idx += 1

        if reload_core_command != 0:
            updates.append(f"reload_core_command = ${param_idx}")
            params.append(reload_core_command)
            param_idx += 1

        if not updates:
            return 200, 'Нет полей для обновления'

        # Всегда обновляем updated_at
        updates.append("updated_at = NOW()")

        query = f"""
        UPDATE nodes_protocols SET {', '.join(updates)}
        WHERE id = ${param_idx}
        RETURNING id
        """
        params.append(np_id)

        try:
            result = await self.conn.fetchval(query, *params)
            if not result:
                return 404, 'Виртуальная нода не найдена'

            return 200, 'Виртуальная нода обновлена'

        except UniqueViolationError:
            return 409, 'Конфликт портов: какой-то из (metrics_port, proto_port) уже занят на этом сервере'

    async def delete_node_protocol(self, np_id: int):
        """Удалить протокол с ноды"""
        query = "DELETE FROM nodes_protocols WHERE id = $1"
        await self.conn.execute(query, np_id)

    async def get_node_for_file_edit(self, node_proto_id: int):
        query = '''
        SELECT n.node_name, np.title, n.ip, n.private_ip, n.api_port, n.is_active, np.user_visible, np.metrics_port, 
               np.proto_port, np.config_path, np.constant_node_data_obj,
               pt.config2json_script, pt.json2config_script, pt.conf_converter_libs, pt.url_tmp
        FROM nodes_protocols np 
        JOIN nodes n ON np.node_id = n.id
        JOIN protocols p ON np.proto_id = p.id
        JOIN proto_templates pt ON p.tmp_id = pt.id
        WHERE np.id = $1
        '''  # noqa: W291
        return await self.conn.fetchrow(query, node_proto_id)

    async def update_config_link(self, node_proto_id: int, sub_ready_link: str):
        query = 'UPDATE nodes_protocols SET updated_at = NOW(), config_link = $2 WHERE id = $1'
        await self.conn.execute(query, node_proto_id, sub_ready_link)

    async def get_core_proto_deps_by_user_sub(
        self, user_uuid: str, user_sub_id: int, node_proto_id: int, operation: Literal['add', 'delete']
    ):
        query = '''
        WITH outbox_insert AS (
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id) 
            SELECT $1, $2, $3, $4
            FROM nodes_protocols np
            JOIN nodes n ON n.id = np.node_id AND n.is_active = true
            WHERE np.reg_status = $5
            RETURNING id, node_proto_id
        ),
        pre_agg_user_injectors AS (
            SELECT tmp_id,
               json_agg(
                   json_build_object(
                       'flatten_array_cursor', flatten_array_cursor,
                       'extractor_script', extractor_script,
                       'libs', libs
                   )
               ) AS user_injectors
            FROM templates_users_extractors
            GROUP BY tmp_id
        )
        SELECT np.id AS node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib, pt.api_bulk_add_user_script,
               pt.api_bulk_delete_user_script, np.reload_core_command,
               np.config_path, pt.required_user_data_obj,
               pt.constant_user_data_obj, pt.bulk_delete_script_custom_params, pt.bulk_add_script_custom_params, oi.id AS event_id,
               np.constant_node_data_obj, pt.json2config_script, pt.config2json_script, pt.conf_converter_libs,
               COALESCE(aui.user_injectors, '[]'::json) AS user_injectors
        FROM nodes_protocols np
        JOIN protocols p ON np.proto_id = p.id
        JOIN nodes n ON np.node_id = n.id AND n.is_active = true
        JOIN proto_templates pt ON p.tmp_id = pt.id
        LEFT JOIN pre_agg_user_injectors aui ON pt.id = aui.tmp_id
        JOIN outbox_insert oi ON oi.node_proto_id = np.id
        WHERE np.id = $4 AND np.reg_status = $5
        '''  # noqa: W291
        return await self.conn.fetchrow(
            query, user_uuid, user_sub_id, CoreProtoActions.name2id[operation], node_proto_id, VnodeRegStatuses.success
        )

    async def reserve_place(
        self,
        proto_id,
        node_id,
        title,
        metrics_port,
        proto_port,
        config_path,
        constant_node_data_obj,
        sub_node_address,
        metrics_command,
        reload_core_command,
    ):
        if constant_node_data_obj is None:
            constant_node_data_obj = {}

        query = '''
        INSERT INTO nodes_protocols (proto_id, node_id, title, config_path, metrics_port, proto_port, sub_node_address, reload_core_command, metrics_command, constant_node_data_obj)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING id, title
        '''
        try:
            vnode = await self.conn.fetchrow(
                query,
                proto_id,
                node_id,
                title,
                config_path,
                metrics_port,
                proto_port,
                sub_node_address,
                reload_core_command,
                metrics_command,
                constant_node_data_obj,
            )
            return True, vnode
        except ForeignKeyViolationError:
            return False, None

    async def confirm_place(
        self,
        node_proto_id: int,
        status: int,
        title: str | None,
        constant_node_data_obj: dict | None | int,
        reload_core_command: str | None,
        metrics_command: str | None,
        config_path: str | None,
        service_name: str | None,
    ):
        if constant_node_data_obj is None:
            constant_node_data_obj = {}

        updates = []
        params = []
        param_idx = 1

        if config_path is not None:
            updates.append(f"config_path = ${param_idx}")
            params.append(config_path)
            param_idx += 1

        if status is not None:
            updates.append(f"reg_status = ${param_idx}")
            params.append(status)
            param_idx += 1

        if title is not None:
            updates.append(f"title = ${param_idx}")
            params.append(title)
            param_idx += 1

        if reload_core_command is not None:
            updates.append(f"reload_core_command = ${param_idx}")
            params.append(reload_core_command)
            param_idx += 1

        if metrics_command is not None:
            updates.append(f"metrics_command = ${param_idx}")
            params.append(metrics_command)
            param_idx += 1

        if service_name is not None:
            updates.append(f"service_name = ${param_idx}")
            params.append(service_name)
            param_idx += 1

        if constant_node_data_obj != 0:
            updates.append(f"constant_node_data_obj = ${param_idx}")
            params.append(constant_node_data_obj)
            param_idx += 1

        updates.append("updated_at = NOW()")
        query = f"""
        UPDATE nodes_protocols SET {', '.join(updates)}
        WHERE id = ${param_idx}
        RETURNING id
        """
        params.append(node_proto_id)

        vnode = await self.conn.fetchval(query, *params)
        return vnode

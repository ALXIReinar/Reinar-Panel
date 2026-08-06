from typing import Literal

from asyncpg import Connection

from web.arq_worker.utils.anything import CoreProtoActions, PayStatuses


class BulkActionsQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def get_users_by_sub_plan(self, outbox_event_ids: list[int], action: Literal['add', 'delete']):
        query = '''
        WITH outbox_plan AS (
            SELECT sno.node_proto_id, sno.user_sub_id, sno.user_uuid AS uuid
            FROM sub_nodes_outbox sno 
            JOIN (
                SELECT event_id FROM UNNEST($1::bigint[]) AS t(event_id)
            ) AS inp_outbox ON sno.id = inp_outbox.event_id
            JOIN user_subs us ON us.id = sno.user_sub_id
            JOIN users u ON u.id = us.user_id AND u.is_deleted = false
            WHERE sno.operation = $2
        )
        SELECT np.id AS node_proto_id, n.private_ip, n.api_port, np.metrics_port, 
               pt.proto_python_lib, pt.flatten_json_users_key, pt.flatten_user_identifier_key, 
               pt.reload_core_command, np.config_path, pt.constant_user_data_obj, pt.required_user_data_obj,
               pt.api_bulk_add_user_script, pt.bulk_add_script_custom_params, pt.api_bulk_delete_user_script, 
               pt.bulk_delete_script_custom_params, pt.process_user_item_script, pt.process_user_libs,
               op.uuid, op.user_sub_id
        FROM nodes_protocols np
        JOIN outbox_plan op ON op.node_proto_id = np.id
        JOIN nodes n ON np.node_id = n.id AND n.is_active = true
        JOIN protocols p ON np.proto_id = p.id 
        JOIN proto_templates pt ON pt.id = p.tmp_id 
        WHERE np.user_visible = true
        '''
        return await self.conn.fetch(query, outbox_event_ids, CoreProtoActions.name2id[action])


    async def get_sub_nodes_for_bulk_action(self, users: list[dict]):
        user_sub_ids, sub_plan_ids, user_uuids = zip(*tuple(u.values() for u in users))
        # user_sub_ids, sub_plan_ids, user_ids = zip(
        #     *tuple(tuple(u['user_sub_id'], u['sub_plan_id'], u['user_id']) for u in users)
        # )
        query = '''
        WITH users_to_proto_cores AS (
            SELECT user_sub_id, sub_plan_id, uuid 
            FROM UNNEST($1::bigint[], $2::integer[], $3::varchar[]) AS t(user_sub_id, sub_plan_id, uuid)
        ),
        -- 2. Собираем информацию о нодах для этих подписок
        expired_nodes_info AS (
            SELECT upc.uuid, upc.user_sub_id,
                   vsp.node_proto_id, n.private_ip, n.api_port, np.metrics_port, 
                   pt.proto_python_lib,
                   pt.flatten_json_users_key, 
                   pt.flatten_user_identifier_key, 
                   pt.reload_core_command,
                   np.config_path, 
                   pt.constant_user_data_obj, 
                   pt.required_user_data_obj,
                   pt.api_bulk_add_user_script,
                   pt.bulk_add_script_custom_params,
                   pt.api_bulk_delete_user_script,
                   pt.bulk_delete_script_custom_params,
                   pt.process_user_item_script, 
                   pt.process_user_libs
            FROM users_to_proto_cores upc
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = upc.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            JOIN protocols p ON np.proto_id = p.id 
            JOIN proto_templates pt ON p.tmp_id = pt.id 
        )
        -- 3. Группируем пользователей по нодам для пакетной отправки
        SELECT node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, 
               flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, 
               constant_user_data_obj, required_user_data_obj, 
               api_bulk_add_user_script, bulk_add_script_custom_params,
               api_bulk_delete_user_script, bulk_delete_script_custom_params,
               process_user_item_script, process_user_libs,
               COALESCE(
                   json_agg(
                       json_build_object( 
                           'uuid', uuid, 
                           'user_sub_id', user_sub_id,
                           'node_proto_id', node_proto_id
                       )
                   ),
                   '[]'::json
               ) AS users
        FROM expired_nodes_info
        GROUP BY node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, 
                 flatten_json_users_key, flatten_user_identifier_key,
                 reload_core_command, config_path, constant_user_data_obj, required_user_data_obj, 
                 api_bulk_add_user_script, bulk_add_script_custom_params,
                 api_bulk_delete_user_script, bulk_delete_script_custom_params,
                 process_user_item_script, process_user_libs
        '''
        return await self.conn.fetch(query, user_sub_ids, sub_plan_ids, user_uuids)


    async def get_and_lock_expired_subs_grouped_by_node(self):
        """
        Атомарно выключает просроченные подписки, фиксирует их в outbox
        и возвращает сгруппированные по нодам данные для bulk-удаления.
        """
        query = '''
        -- 1. Выключаем просроченные подписки и возвращаем их ID и данные юзеров(Не трогаем бессрочные подписки)
        WITH deactivated_subs AS (
            UPDATE user_subs us
            SET is_active = false
            FROM users u
            WHERE us.user_id = u.id
              AND us.is_active = true
              AND u.is_deleted = false
              AND ((us.expire_date < now() AND us.infinite_expire = false)
                  OR (us.used_mb >= us.used_mb_limit AND us.infinite_traffic = false))
            RETURNING us.id AS user_sub_id, us.sub_plan_id, us.uuid, us.order_id
        ),
        -- 2.Помечаем платёж в общей истории
        change_order_status AS (
            UPDATE pay_orders SET status = $2 
            FROM (SELECT order_id FROM deactivated_subs) AS ds2
            WHERE id = ds2.order_id
        ),
        -- 3. Собираем информацию о нодах для этих подписок
        expired_nodes_info AS (
            SELECT ds.uuid, ds.user_sub_id, vsp.node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
                   pt.api_bulk_delete_user_script, pt.bulk_delete_script_custom_params, pt.flatten_json_users_key, pt.flatten_user_identifier_key,
                   pt.reload_core_command, np.config_path, pt.constant_user_data_obj, pt.required_user_data_obj,
                   pt.process_user_item_script, pt.process_user_libs
            FROM deactivated_subs ds
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = ds.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            JOIN protocols p ON np.proto_id = p.id 
            JOIN proto_templates pt ON p.tmp_id = pt.id 
        ),
        -- 4. Фиксируем операцию удаления в outbox (двухэтапный ack)
        insert_outbox AS (
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            SELECT uuid, user_sub_id, $1, node_proto_id
            FROM expired_nodes_info
        )
        -- 5. Группируем пользователей по нодам для пакетной отправки
        SELECT node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, api_bulk_delete_user_script, 
               flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, bulk_delete_script_custom_params,
               constant_user_data_obj, required_user_data_obj, process_user_item_script, process_user_libs,
               COALESCE(
                   json_agg(
                       json_build_object( 
                           'uuid', uuid, 
                           'user_sub_id', user_sub_id,
                           'node_proto_id', node_proto_id
                       )
                   ),
                   '[]'::json
               ) AS users
        FROM expired_nodes_info
        GROUP BY node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, api_bulk_delete_user_script, 
                 flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, constant_user_data_obj,
                 required_user_data_obj, process_user_item_script, process_user_libs, bulk_delete_script_custom_params
        '''
        return await self.conn.fetch(query, CoreProtoActions.delete, PayStatuses.expired)


    async def success_bulk_action_core_proto_users(self, node_proto_ids: list[int], user_sub_ids: list[int], action: CoreProtoActions | int):
        query = '''
        DELETE FROM sub_nodes_outbox
        WHERE node_proto_id = ANY ($1)
          AND user_sub_id = ANY ($2)
          AND operation = $3
        '''
        await self.conn.execute(query, node_proto_ids, user_sub_ids, action)



class SingleActionsQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def success_action_core_proto_user(self, node_proto_ids: list[int], operation: Literal['add', 'delete'], user_uuid: str):
        if not node_proto_ids:
            return

        query = 'DELETE FROM sub_nodes_outbox WHERE user_uuid = $3 AND operation = $2 AND node_proto_id = ANY ($1)'
        await self.conn.execute(query, node_proto_ids, CoreProtoActions.name2id[operation], user_uuid)


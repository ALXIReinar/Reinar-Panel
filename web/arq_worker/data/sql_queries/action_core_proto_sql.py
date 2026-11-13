from asyncpg import Connection

from web.arq_worker.utils.anything import CoreProtoActions, PayStatuses, VnodeRegStatuses


class BulkActionsQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def get_meta_for_bulk(self, outbox_event_ids: list[int]):
        query = '''
        -- 1. Пре-агрегация! Теперь у нас по одной записи на каждый node_proto_id с готовым JSON-массивом пользователей
        WITH pre_aggregated_users AS (
            SELECT node_proto_id,
                json_agg(
                    json_build_object( 
                        'uuid', user_uuid, 
                        'user_sub_id', user_sub_id,
                        'event_id', id
                    )
                ) AS users
            FROM sub_nodes_outbox
            WHERE id = ANY($1)
            GROUP BY node_proto_id
        )
        -- 2. Финальный джойн. 
        SELECT np.id AS node_proto_id, n.private_ip, n.api_port, np.metrics_port, 
               pt.constant_user_data_obj, pt.required_user_data_obj,
               pt.bulk_add_script_custom_params, np.constant_node_data_obj,
               pt.bulk_delete_script_custom_params,
               COALESCE(pau.users, '[]'::json) AS users
        FROM nodes_protocols np
        JOIN pre_aggregated_users pau ON pau.node_proto_id = np.id
        JOIN nodes n ON np.node_id = n.id AND n.is_active = true
        JOIN proto_templates pt ON np.tmp_id = pt.id 
        WHERE np.user_visible = true AND np.reg_status = $2
        '''  # noqa: W291
        return await self.conn.fetch(query, outbox_event_ids, VnodeRegStatuses.success)

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
            WHERE pay_orders.id = ds2.order_id AND ds2.order_id IS NOT NULL
        ),
        -- 4. Фиксируем операцию удаления в outbox (двухэтапный ack)
        insert_outbox AS (
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            SELECT ds.uuid, ds.user_sub_id, $1, vsp.node_proto_id
            FROM deactivated_subs ds
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = ds.sub_plan_id
            RETURNING id AS event_id, user_sub_id, user_uuid, node_proto_id
        ),
        -- 5. Пре-агрегация пользователей. Самая последняя, т.к. записей больше всех остальных пре-агрегаций
        pre_agg_users AS (
            SELECT node_proto_id,
                   json_agg(
                        json_build_object(
                            'event_id', event_id,
                            'uuid', user_uuid,
                            'user_sub_id', user_sub_id
                        )
                   ) AS users
            FROM insert_outbox
            GROUP BY node_proto_id
        )
        -- 6. Группируем пользователей по нодам для пакетной отправки
        SELECT np.id AS node_proto_id, n.private_ip, n.api_port, np.metrics_port, 
               pt.bulk_delete_script_custom_params, pt.constant_user_data_obj, pt.required_user_data_obj,
               pau.users, np.constant_node_data_obj
        FROM nodes_protocols np
        JOIN nodes n ON n.id = np.node_id AND n.is_active = true
        JOIN pre_agg_users pau ON pau.node_proto_id = np.id
        JOIN proto_templates pt ON np.tmp_id = pt.id 
        WHERE np.user_visible = true AND np.reg_status = $3
        '''  # noqa: W291
        return await self.conn.fetch(query, CoreProtoActions.delete, PayStatuses.expired, VnodeRegStatuses.success)

    async def success_bulk_action_core_proto_users(self, outbox_event_ids: list[int]):
        if not outbox_event_ids:
            return

        query = 'DELETE FROM sub_nodes_outbox WHERE id = ANY ($1)'
        await self.conn.execute(query, outbox_event_ids)

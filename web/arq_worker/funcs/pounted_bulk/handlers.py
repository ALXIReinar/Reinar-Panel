
def group_users_by_node_proto_id(node_protos_users: list):
    """
    "Это" на питоне делает вот это в sql
    SELECT ..., ni.bulk_delete_script_custom_params,
        COALESCE(
            json_agg(
                json_build_object(
                    'uuid', up.uuid,
                    'user_sub_id', up.user_sub_id,
                    'node_proto_id', ni.node_proto_id
                )
            ),
            '[]'::json
        ) AS users
    FROM nodes_info ni
    JOIN users_plan up ON up.sub_plan_id = ni.sub_plan_id
    GROUP BY ni.node_proto_id
    """
    nodes_map = {}

    for row in node_protos_users:
        node_id = row['node_proto_id']

        if node_id not in nodes_map:
            # Копируем метаданные ноды (без полей юзера)
            node_data = dict(row)
            node_data.pop('uuid')
            node_data.pop('user_sub_id')
            node_data['users'] = []
            nodes_map[node_id] = node_data

        # Добавляем юзера в список соответствующей ноды
        nodes_map[node_id]['users'].append({
            'uuid': row['uuid'],
            'user_sub_id': row['user_sub_id'],
            'node_proto_id': node_id
        })

    return list(nodes_map.values())
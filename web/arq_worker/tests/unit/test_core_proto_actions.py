"""
Unit тесты выбора custom_params скрипта шаблона по операции (бэклог F4)

Операции — только add(1) и delete(2) из sub_nodes_operations. Выбор строгий: у каждой операции своё поле шаблона,
неизвестная операция не превращается молча в add.
"""

import pytest

from web.arq_worker.utils.anything import CoreProtoActions

VNODE = {
    'bulk_add_script_custom_params': {'inbound_tag': 'add-tag'},
    'bulk_delete_script_custom_params': {'inbound_tag': 'delete-tag'},
}


@pytest.mark.parametrize(
    ('operation', 'expected'),
    [
        (CoreProtoActions.add, {'inbound_tag': 'add-tag'}),
        (CoreProtoActions.delete, {'inbound_tag': 'delete-tag'}),
    ],
)
def test_custom_params_by_operation(operation, expected):
    assert CoreProtoActions.custom_params(VNODE, operation) == expected


def test_custom_params_by_word_via_name2id():
    """Продюсеры передают слова 'add'/'delete' — они переводятся в ID операции той же таблицей name2id"""
    assert CoreProtoActions.custom_params(VNODE, CoreProtoActions.name2id['delete']) == {'inbound_tag': 'delete-tag'}


@pytest.mark.parametrize('operation', [0, 3, 'delete', 'reset_traffic'])
def test_unknown_operation_is_not_add(operation):
    """Неизвестная операция (или слово вместо ID) — ошибка продюсера, а не параметры add"""
    with pytest.raises(KeyError):
        CoreProtoActions.custom_params(VNODE, operation)


def test_template_without_params_gives_none():
    """У шаблона нет custom_params для операции (NULL в БД) — скрипт получит None, как и раньше"""
    vnode = {'bulk_add_script_custom_params': None, 'bulk_delete_script_custom_params': None}
    assert CoreProtoActions.custom_params(vnode, CoreProtoActions.add) is None

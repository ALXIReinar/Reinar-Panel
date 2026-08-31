from typing import Optional
import datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKeyConstraint, Identity, Index, Integer, PrimaryKeyConstraint, SmallInteger, String, Text, Time, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass


class Admins(Base):
    __tablename__ = 'admins'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='users_pkey'),
        UniqueConstraint('login', name='admins_login_key')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    passw: Mapped[str] = mapped_column(String(97), nullable=False)
    login: Mapped[str] = mapped_column(String(128), nullable=False)
    date_register: Mapped[Optional[datetime.date]] = mapped_column(Date, server_default=text('(now())::date'))

    sessions_admins: Mapped[list['SessionsAdmins']] = relationship('SessionsAdmins', back_populates='admin')
    protocols_commands: Mapped[list['ProtocolsCommands']] = relationship('ProtocolsCommands', back_populates='admin')


class Nodes(Base):
    __tablename__ = 'nodes'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='nodes_pkey1'),
        UniqueConstraint('ip', name='nodes_ip_key'),
        UniqueConstraint('private_ip', name='nodes_private_ip_key')
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=32767, cycle=False, cache=1), primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(String(45), nullable=False)
    api_port: Mapped[int] = mapped_column(Integer, nullable=False)
    private_ip: Mapped[Optional[str]] = mapped_column(String(45))
    is_active: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('true'))
    title: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True), server_default=text('now()'))
    updated_at: Mapped[Optional[datetime.time]] = mapped_column(Time(True), server_default=text('now()'))
    node_name: Mapped[Optional[str]] = mapped_column(String(64))

    nodes_protocols: Mapped[list['NodesProtocols']] = relationship('NodesProtocols', back_populates='node')


class OnlineStatuses(Base):
    __tablename__ = 'online_statuses'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='online_statuses_pkey'),
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=32767, cycle=False, cache=1), primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(32), nullable=False)

    users: Mapped[list['Users']] = relationship('Users', back_populates='online_statuses')


class PayStatuses(Base):
    __tablename__ = 'pay_statuses'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='pay_statuses_pkey'),
        UniqueConstraint('name', name='pay_statuses_name_key')
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=32767, cycle=False, cache=1), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(20), nullable=False)

    pay_orders: Mapped[list['PayOrders']] = relationship('PayOrders', back_populates='pay_statuses')


class RemoteExecuteHistory(Base):
    __tablename__ = 'remote_execute_history'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='remote_execute_history_pkey'),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    command: Mapped[str] = mapped_column(String(1024), nullable=False)
    stdout: Mapped[Optional[str]] = mapped_column(Text)
    stderr: Mapped[Optional[str]] = mapped_column(Text)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, server_default=text('1'))
    exception_text: Mapped[Optional[str]] = mapped_column(Text)
    node_proto_id: Mapped[Optional[int]] = mapped_column(Integer)
    api_port: Mapped[Optional[int]] = mapped_column(Integer)
    private_ip: Mapped[Optional[str]] = mapped_column(String(45))
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True), server_default=text('now()'))
    status_code: Mapped[Optional[int]] = mapped_column(SmallInteger, server_default=text('100'))
    node_success: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True), server_default=text('now()'))


class SubNodesOperations(Base):
    __tablename__ = 'sub_nodes_operations'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='add_core_proto_statuses_pkey'),
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=32767, cycle=False, cache=1), primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(20), nullable=False)


class SubPlans(Base):
    __tablename__ = 'sub_plans'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='sub_plans_pkey'),
        UniqueConstraint('title', name='sub_plans_title_key'),
        Index('sub_plans_position_idx', 'position', postgresql_where='(is_active = true)', postgresql_with={'deduplicate_items': 'true'}, unique=True)
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1), primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(25), nullable=False)
    is_active: Mapped[Optional[bool]] = mapped_column(Boolean)
    description: Mapped[Optional[str]] = mapped_column(String(200))
    position: Mapped[Optional[int]] = mapped_column(SmallInteger, server_default=text('0'))

    sub_plan_offers: Mapped[list['SubPlanOffers']] = relationship('SubPlanOffers', back_populates='sub_plan')
    user_subs: Mapped[list['UserSubs']] = relationship('UserSubs', back_populates='sub_plan')
    vnodes_sub_plans: Mapped[list['VnodesSubPlans']] = relationship('VnodesSubPlans', back_populates='sub_plan')


class TemplatesStatuses(Base):
    __tablename__ = 'templates_statuses'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='pattern_statuses_pkey'),
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=32767, cycle=False, cache=1), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)

    proto_templates: Mapped[list['ProtoTemplates']] = relationship('ProtoTemplates', back_populates='templates_statuses')


class WhitelistCommands(Base):
    __tablename__ = 'whitelist_commands'
    __table_args__ = (
        PrimaryKeyConstraint('id', name='whitelist_commands_pkey'),
        UniqueConstraint('command', name='whitelist_commands_command_key')
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1), primary_key=True, autoincrement=True)
    command: Mapped[str] = mapped_column(String(1000), nullable=False)
    is_active: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('true'))


class ProtoTemplates(Base):
    __tablename__ = 'proto_templates'
    __table_args__ = (
        ForeignKeyConstraint(['status'], ['templates_statuses.id'], ondelete='RESTRICT', name='proto_templates_status_fkey'),
        PrimaryKeyConstraint('id', name='proto_templates_pkey'),
        UniqueConstraint('title', name='proto_templates_title_key')
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=32767, cycle=False, cache=1), primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text('2'))
    url_tmp: Mapped[Optional[str]] = mapped_column(Text)
    is_accepted: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    reload_core_command: Mapped[Optional[str]] = mapped_column(String(128))
    required_user_data_obj: Mapped[Optional[dict]] = mapped_column(JSONB)
    constant_user_data_obj: Mapped[Optional[dict]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    proto_python_lib: Mapped[Optional[str]] = mapped_column(String(512))
    sub_prepare_script: Mapped[Optional[str]] = mapped_column(Text)
    sub_required_libs: Mapped[Optional[str]] = mapped_column(String(512))
    api_bulk_delete_user_script: Mapped[Optional[str]] = mapped_column(Text)
    metrics_parser_code: Mapped[Optional[str]] = mapped_column(Text)
    metrics_command: Mapped[Optional[str]] = mapped_column(String(256))
    bulk_delete_script_custom_params: Mapped[Optional[dict]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    api_metrics_script: Mapped[Optional[str]] = mapped_column(Text)
    api_bulk_add_user_script: Mapped[Optional[str]] = mapped_column(Text)
    bulk_add_script_custom_params: Mapped[Optional[dict]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    description: Mapped[Optional[str]] = mapped_column(Text)
    metrics_parser_libs: Mapped[Optional[str]] = mapped_column(String(512))
    config2json_script: Mapped[Optional[str]] = mapped_column(Text)
    json2config_script: Mapped[Optional[str]] = mapped_column(Text)
    conf_converter_libs: Mapped[Optional[str]] = mapped_column(String(512))

    templates_statuses: Mapped['TemplatesStatuses'] = relationship('TemplatesStatuses', back_populates='proto_templates')
    protocols: Mapped[list['Protocols']] = relationship('Protocols', back_populates='tmp')
    templates_users_extractors: Mapped[list['TemplatesUsersExtractors']] = relationship('TemplatesUsersExtractors', back_populates='tmp')


class SessionsAdmins(Base):
    __tablename__ = 'sessions_admins'
    __table_args__ = (
        ForeignKeyConstraint(['admin_id'], ['admins.id'], ondelete='CASCADE', name='sessions_users_user_id_fkey'),
        PrimaryKeyConstraint('session_id', name='sessions_users_pkey'),
        UniqueConstraint('refresh_token', name='sessions_users_refresh_token_key'),
        UniqueConstraint('session_id', 'admin_id', name='sessions_users_session_id_user_id_key')
    )

    session_id: Mapped[str] = mapped_column(Text, primary_key=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    iat: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    exp: Mapped[datetime.datetime] = mapped_column(DateTime(True), nullable=False)
    refresh_token: Mapped[str] = mapped_column(String(97), nullable=False)
    ip: Mapped[str] = mapped_column(String(45), nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(String(200))

    admin: Mapped['Admins'] = relationship('Admins', back_populates='sessions_admins')


class SubPlanOffers(Base):
    __tablename__ = 'sub_plan_offers'
    __table_args__ = (
        ForeignKeyConstraint(['sub_plan_id'], ['sub_plans.id'], ondelete='CASCADE', name='sub_plan_offers_sub_plan_id_fkey'),
        PrimaryKeyConstraint('id', name='sub_plan_offers_pkey'),
        Index('sub_plan_offers_position_sub_plan_id_idx', 'position', 'sub_plan_id', postgresql_where='(is_active = true)', postgresql_with={'deduplicate_items': 'true'}, unique=True)
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1), primary_key=True, autoincrement=True)
    sub_plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ttl_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    cost: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_active: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    traffic_limit_day_mb: Mapped[Optional[int]] = mapped_column(BigInteger)
    traffic_limit_mb: Mapped[Optional[int]] = mapped_column(BigInteger)
    infinite_traffic: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    infinite_expire: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    position: Mapped[Optional[int]] = mapped_column(SmallInteger)

    sub_plan: Mapped['SubPlans'] = relationship('SubPlans', back_populates='sub_plan_offers')


class Users(Base):
    __tablename__ = 'users'
    __table_args__ = (
        ForeignKeyConstraint(['online_status'], ['online_statuses.id'], ondelete='RESTRICT', name='users_online_status_fkey'),
        PrimaryKeyConstraint('id', name='users_pkey1'),
        UniqueConstraint('tg_id', name='users_tg_id_key'),
        UniqueConstraint('tg_username', name='users_tg_username_key'),
        Index('users_tg_id_idx', 'tg_id', postgresql_where='(is_deleted = false)', postgresql_with={'deduplicate_items': 'true'}, unique=True),
        Index('users_tg_username_idx', 'tg_username', postgresql_where='(is_deleted = false)', postgresql_with={'deduplicate_items': 'true'}, unique=True)
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    online_status: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text('1'))
    tg_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    tg_username: Mapped[Optional[str]] = mapped_column(String(32))
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True), server_default=text('now()'))
    registered_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True), server_default=text('now()'))
    is_deleted: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))

    online_statuses: Mapped['OnlineStatuses'] = relationship('OnlineStatuses', back_populates='users')
    pay_orders: Mapped[list['PayOrders']] = relationship('PayOrders', back_populates='user')
    user_subs: Mapped[list['UserSubs']] = relationship('UserSubs', back_populates='user')


class PayOrders(Base):
    __tablename__ = 'pay_orders'
    __table_args__ = (
        ForeignKeyConstraint(['status'], ['pay_statuses.id'], name='pay_orders_status_fkey'),
        ForeignKeyConstraint(['user_id'], ['users.id'], name='pay_orders_user_id_fkey'),
        PrimaryKeyConstraint('id', name='pay_orders_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    infinite_expire: Mapped[bool] = mapped_column(Boolean, nullable=False)
    infinite_traffic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cost: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[Optional[int]] = mapped_column(SmallInteger, server_default=text('1'))
    timestamp: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True), server_default=text('now()'))
    traffic_limit_mb: Mapped[Optional[int]] = mapped_column(BigInteger)
    traffic_limit_day_mb: Mapped[Optional[int]] = mapped_column(BigInteger)
    ttl_days: Mapped[Optional[int]] = mapped_column(SmallInteger)

    pay_statuses: Mapped[Optional['PayStatuses']] = relationship('PayStatuses', back_populates='pay_orders')
    user: Mapped['Users'] = relationship('Users', back_populates='pay_orders')
    user_subs: Mapped[list['UserSubs']] = relationship('UserSubs', back_populates='order')


class Protocols(Base):
    __tablename__ = 'protocols'
    __table_args__ = (
        ForeignKeyConstraint(['tmp_id'], ['proto_templates.id'], ondelete='RESTRICT', name='protocols_proto_tmp_id_fkey'),
        PrimaryKeyConstraint('id', name='protocols_pkey'),
        UniqueConstraint('name', name='protocols_name_key'),
        {'comment': 'Пул поддерживаемых VPN протоколов'}
    )

    id: Mapped[int] = mapped_column(SmallInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=32767, cycle=False, cache=1), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment='Название протокола (xray, wireguard, openvpn и т.д.)')
    tmp_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, server_default=text('now()'))

    tmp: Mapped['ProtoTemplates'] = relationship('ProtoTemplates', back_populates='protocols')
    nodes_protocols: Mapped[list['NodesProtocols']] = relationship('NodesProtocols', back_populates='proto')
    protocols_commands: Mapped[list['ProtocolsCommands']] = relationship('ProtocolsCommands', back_populates='proto')


class TemplatesUsersExtractors(Base):
    __tablename__ = 'templates_users_extractors'
    __table_args__ = (
        ForeignKeyConstraint(['tmp_id'], ['proto_templates.id'], ondelete='CASCADE', name='templates_users_extractors_tmp_id_fkey'),
        PrimaryKeyConstraint('id', name='templates_users_extractors_pkey'),
        UniqueConstraint('tmp_id', 'flatten_array_cursor', name='templates_users_extractors_tmp_id_flatten_array_cursor_key')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    tmp_id: Mapped[int] = mapped_column(Integer, nullable=False)
    flatten_array_cursor: Mapped[str] = mapped_column(String(1024), nullable=False)
    extractor_script: Mapped[str] = mapped_column(Text, nullable=False)
    libs: Mapped[Optional[str]] = mapped_column(String(512))

    tmp: Mapped['ProtoTemplates'] = relationship('ProtoTemplates', back_populates='templates_users_extractors')


class NodesProtocols(Base):
    __tablename__ = 'nodes_protocols'
    __table_args__ = (
        ForeignKeyConstraint(['node_id'], ['nodes.id'], ondelete='CASCADE', name='nodes_protocols_node_id_fkey'),
        ForeignKeyConstraint(['proto_id'], ['protocols.id'], ondelete='RESTRICT', name='nodes_proto_id_fkey'),
        PrimaryKeyConstraint('id', name='nodes_pkey'),
        UniqueConstraint('config_path', 'node_id', name='nodes_protocols_config_path_node_id_key'),
        UniqueConstraint('node_id', 'metrics_port', name='nodes_protocols_node_id_metrics_port_key'),
        UniqueConstraint('node_id', 'proto_port', name='nodes_protocols_node_id_proto_port_key')
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1), primary_key=True, autoincrement=True)
    proto_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    node_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("''::character varying"))
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True), server_default=text('now()'))
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True), server_default=text('now()'))
    config_path: Mapped[Optional[str]] = mapped_column(Text)
    user_visible: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    config_link: Mapped[Optional[str]] = mapped_column(Text)
    metrics_port: Mapped[Optional[int]] = mapped_column(Integer)
    proto_port: Mapped[Optional[int]] = mapped_column(Integer)
    sub_node_address: Mapped[Optional[str]] = mapped_column(String(255))
    constant_node_data_obj: Mapped[Optional[dict]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    reload_core_command: Mapped[Optional[str]] = mapped_column(String(256))
    metrics_command: Mapped[Optional[str]] = mapped_column(String(256))

    node: Mapped['Nodes'] = relationship('Nodes', back_populates='nodes_protocols')
    proto: Mapped['Protocols'] = relationship('Protocols', back_populates='nodes_protocols')
    sub_nodes_outbox: Mapped[list['SubNodesOutbox']] = relationship('SubNodesOutbox', back_populates='node_proto')
    vnodes_sub_plans: Mapped[list['VnodesSubPlans']] = relationship('VnodesSubPlans', back_populates='node_proto')


class ProtocolsCommands(Base):
    __tablename__ = 'protocols_commands'
    __table_args__ = (
        ForeignKeyConstraint(['admin_id'], ['admins.id'], name='protocols_commands_admin_id_fkey'),
        ForeignKeyConstraint(['proto_id'], ['protocols.id'], ondelete='CASCADE', name='protocols_commands_proto_id_fkey'),
        PrimaryKeyConstraint('id', name='protocols_commands_pkey'),
        {'comment': 'CLI команды для управления протоколами'}
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    proto_id: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment='ID протокола')
    cmd_title: Mapped[str] = mapped_column(String(200), nullable=False, comment='Название команды (add_user, remove_user, restart и т.д.)')
    command: Mapped[str] = mapped_column(Text, nullable=False, comment='Полная CLI команда для выполнения. Валидация не производится - ответственность администратора')
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, server_default=text('now()'))
    admin_id: Mapped[Optional[int]] = mapped_column(BigInteger)

    admin: Mapped[Optional['Admins']] = relationship('Admins', back_populates='protocols_commands')
    proto: Mapped['Protocols'] = relationship('Protocols', back_populates='protocols_commands')


class UserSubs(Base):
    __tablename__ = 'user_subs'
    __table_args__ = (
        ForeignKeyConstraint(['order_id'], ['pay_orders.id'], ondelete='CASCADE', name='user_subs_order_id_fkey'),
        ForeignKeyConstraint(['sub_plan_id'], ['sub_plans.id'], ondelete='RESTRICT', name='user_subs_sub_plan_id_fkey'),
        ForeignKeyConstraint(['user_id'], ['users.id'], name='user_subs_user_id_fkey'),
        PrimaryKeyConstraint('id', name='user_subs_pkey'),
        UniqueConstraint('b64_id', name='user_subs_b64_id_key'),
        UniqueConstraint('user_id', 'sub_plan_id', name='user_subs_user_id_sub_plan_id_key'),
        UniqueConstraint('uuid', name='user_subs_uuid_key')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sub_plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    infinite_traffic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    b64_id: Mapped[str] = mapped_column(String(150), nullable=False)
    infinite_expire: Mapped[bool] = mapped_column(Boolean, nullable=False)
    order_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    is_active: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    is_limited: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    expire_date: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True))
    traffic_used_day_mb: Mapped[Optional[int]] = mapped_column(BigInteger, server_default=text('0'))
    traffic_limit_day: Mapped[Optional[int]] = mapped_column(BigInteger)
    used_mb: Mapped[Optional[int]] = mapped_column(BigInteger, server_default=text('0'))
    used_mb_limit: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True), server_default=text('now()'))

    order: Mapped[Optional['PayOrders']] = relationship('PayOrders', back_populates='user_subs')
    sub_plan: Mapped['SubPlans'] = relationship('SubPlans', back_populates='user_subs')
    user: Mapped['Users'] = relationship('Users', back_populates='user_subs')
    sub_nodes_outbox: Mapped[list['SubNodesOutbox']] = relationship('SubNodesOutbox', back_populates='user_sub')


class SubNodesOutbox(Base):
    __tablename__ = 'sub_nodes_outbox'
    __table_args__ = (
        ForeignKeyConstraint(['node_proto_id'], ['nodes_protocols.id'], ondelete='CASCADE', name='sub_nodes_outbox_node_proto_id_fkey'),
        ForeignKeyConstraint(['user_sub_id'], ['user_subs.id'], ondelete='CASCADE', name='sub_nodes_outbox_user_sub_id_fkey'),
        PrimaryKeyConstraint('id', name='sub_nodes_outbox_pkey')
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=9223372036854775807, cycle=False, cache=1), primary_key=True, autoincrement=True)
    user_uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    operation: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    user_sub_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    node_proto_id: Mapped[int] = mapped_column(Integer, nullable=False)
    is_retried: Mapped[Optional[bool]] = mapped_column(Boolean, server_default=text('false'))
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(True), server_default=text('now()'))

    node_proto: Mapped['NodesProtocols'] = relationship('NodesProtocols', back_populates='sub_nodes_outbox')
    user_sub: Mapped['UserSubs'] = relationship('UserSubs', back_populates='sub_nodes_outbox')


class VnodesSubPlans(Base):
    __tablename__ = 'vnodes_sub_plans'
    __table_args__ = (
        ForeignKeyConstraint(['node_proto_id'], ['nodes_protocols.id'], name='vnodes_sub_plans_node_proto_id_fkey'),
        ForeignKeyConstraint(['sub_plan_id'], ['sub_plans.id'], ondelete='CASCADE', name='vnodes_sub_plans_sub_plan_id_fkey'),
        PrimaryKeyConstraint('id', name='vnodes_sub_plans_pkey'),
        UniqueConstraint('node_proto_id', 'sub_plan_id', name='vnodes_sub_plans_node_proto_id_sub_plan_id_key')
    )

    id: Mapped[int] = mapped_column(Integer, Identity(always=True, start=1, increment=1, minvalue=1, maxvalue=2147483647, cycle=False, cache=1), primary_key=True, autoincrement=True)
    node_proto_id: Mapped[int] = mapped_column(Integer, nullable=False)
    sub_plan_id: Mapped[int] = mapped_column(Integer, nullable=False)

    node_proto: Mapped['NodesProtocols'] = relationship('NodesProtocols', back_populates='vnodes_sub_plans')
    sub_plan: Mapped['SubPlans'] = relationship('SubPlans', back_populates='vnodes_sub_plans')

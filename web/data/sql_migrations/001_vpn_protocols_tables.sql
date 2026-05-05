-- ============================================
-- VPN Protocols Management Tables
-- ============================================

-- Таблица протоколов
CREATE TABLE IF NOT EXISTS protocols (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE protocols IS 'Пул поддерживаемых VPN протоколов';
COMMENT ON COLUMN protocols.name IS 'Название протокола (xray, wireguard, openvpn и т.д.)';


-- Таблица команд протоколов
CREATE TABLE IF NOT EXISTS protocols_commands (
    id SERIAL PRIMARY KEY,
    proto_id INTEGER NOT NULL REFERENCES protocols(id) ON DELETE CASCADE,
    cmd_title VARCHAR(200) NOT NULL,
    command TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(proto_id, cmd_title)
);

COMMENT ON TABLE protocols_commands IS 'CLI команды для управления протоколами';
COMMENT ON COLUMN protocols_commands.proto_id IS 'ID протокола';
COMMENT ON COLUMN protocols_commands.cmd_title IS 'Название команды (add_user, remove_user, restart и т.д.)';
COMMENT ON COLUMN protocols_commands.command IS 'Полная CLI команда для выполнения. Валидация не производится - ответственность администратора';

CREATE INDEX idx_protocols_commands_proto_id ON protocols_commands(proto_id);


-- Таблица нод
-- ВАЖНО: Одна нода = один протокол на одном физическом сервере
-- Это позволяет гибко комбинировать протоколы в подписках
CREATE TABLE IF NOT EXISTS nodes (
    id SERIAL PRIMARY KEY,
    proto_id INTEGER NOT NULL REFERENCES protocols(id) ON DELETE RESTRICT,
    ip VARCHAR(45) NOT NULL,
    port INTEGER,
    title VARCHAR(200) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'vpn_worker',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT chk_node_status CHECK (status IN ('main', 'vpn_worker', 'balancer'))
);

COMMENT ON TABLE nodes IS 'Ноды для распределённого управления VPN. Одна нода = один протокол на одном сервере';
COMMENT ON COLUMN nodes.proto_id IS 'ID протокола, который работает на этой ноде';
COMMENT ON COLUMN nodes.ip IS 'IP адрес физического сервера (может повторяться для разных протоколов)';
COMMENT ON COLUMN nodes.port IS 'Порт протокола на сервере (опционально)';
COMMENT ON COLUMN nodes.title IS 'Человекочитаемое название ноды (например: "Server-1 VLESS", "Server-1 Hysteria2")';
COMMENT ON COLUMN nodes.status IS 'Роль ноды: main - главная, vpn_worker - рабочая нода, balancer - балансировщик';

CREATE INDEX idx_nodes_status ON nodes(status);
CREATE INDEX idx_nodes_proto_id ON nodes(proto_id);
CREATE INDEX idx_nodes_ip ON nodes(ip);


-- Таблица конфигураций протоколов на нодах
CREATE TABLE IF NOT EXISTS proto_configs (
    id SERIAL PRIMARY KEY,
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(node_id)
);

COMMENT ON TABLE proto_configs IS 'Пути к конфигурационным файлам протоколов на нодах (версионирование)';
COMMENT ON COLUMN proto_configs.node_id IS 'ID ноды (уже содержит привязку к протоколу)';
COMMENT ON COLUMN proto_configs.path IS 'Путь к конфигурационному файлу на ноде';

CREATE INDEX idx_proto_configs_node_id ON proto_configs(node_id);


-- ============================================
-- Примеры данных для популярных протоколов
-- ============================================

-- Xray/V2Ray
INSERT INTO protocols (name) VALUES ('xray') ON CONFLICT (name) DO NOTHING;

-- WireGuard
INSERT INTO protocols (name) VALUES ('wireguard') ON CONFLICT (name) DO NOTHING;

-- OpenVPN
INSERT INTO protocols (name) VALUES ('openvpn') ON CONFLICT (name) DO NOTHING;

-- Shadowsocks
INSERT INTO protocols (name) VALUES ('shadowsocks') ON CONFLICT (name) DO NOTHING;

-- Hysteria2
INSERT INTO protocols (name) VALUES ('hysteria2') ON CONFLICT (name) DO NOTHING;


-- ============================================
-- Пример: Один сервер с двумя протоколами
-- ============================================
-- INSERT INTO nodes (proto_id, ip, port, title, status) VALUES 
-- (1, '192.168.1.100', 443, 'Server-1 VLESS', 'vpn_worker'),
-- (5, '192.168.1.100', 8443, 'Server-1 Hysteria2', 'vpn_worker');

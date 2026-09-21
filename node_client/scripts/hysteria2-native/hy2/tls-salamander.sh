#!/bin/bash

log() { echo -e "$1" >&2; }


if [ -z "$NODE_ID" ] || [ -z "$PROTO_ID" ]; then
    log "Необходимо указать переменные окружения NODE_ID, PROTO_ID !"
    exit 1
fi

if [ -z "$CERT_PATH" ] || [ -z "$KEY_PATH" ] || [ -z "$DOMAIN" ] || [ -z "$SERVICES_LIST" ]; then
    log "Ошибка: Необходимо предварительно выпустить сертификат (bash issue_cert_acme.sh)!"
    exit 1
fi

if [ -z "$TITLE" ]; then
    log "Название для виртуальной ноды не указано. Будет использовано составное"
    TITLE="Vnode_PrId-'$PROTO_ID'_NId-'$NODE_ID'"
fi

OBFS_PASS=$(openssl rand -hex 8)
HYSTERIA_BIN="/usr/local/bin/hysteria"
CONFIG_DIR="/etc/reinar/configs/hysteria/hy2"
PANEL_CALLBACK_URL="http://10.0.0.1:$ADMIN_PANEL_PORT/api/v1/server/nodes/protocols/register"
PANEL_CONFIRM_URL="http://10.0.0.1:$ADMIN_PANEL_PORT/api/v1/server/nodes/protocols/confirm"

mkdir -p "$CONFIG_DIR"

# Функция поиска свободного одиночного порта
find_free_port() {
    local port=$1
    while ss -lntu | awk '{print $4}' | grep -q ":$port$"; do
        port=$((port + 1))
    done
    echo $port
}

# Ищем свободный внутренний порт для Hysteria
INTERNAL_PORT=$(find_free_port 8443)
METRICS_PORT=$(find_free_port 10085)
METRICS_TOKEN=$(openssl rand -hex 8)

log "Выделен внутренний порт для Hysteria: $INTERNAL_PORT"

log "1. Регистрация ноды в панели и получение node_proto_id..."

REG_RESPONSE=$(mktemp)
HTTP_CODE=$(curl -s -w "%{http_code}" -o "$REG_RESPONSE" -X POST "$PANEL_CALLBACK_URL" \
     -H "Content-Type: application/json" \
     -d '{
           "proto_id": "'"$PROTO_ID"'",
           "node_id": "'"$NODE_ID"'",
           "proto_port": '"$INTERNAL_PORT"',
           "metrics_port": '"$METRICS_PORT"',
           "title": "'"$TITLE"'",
           "metrics_command" : "curl \"http://127.0.0.1:'"$METRICS_PORT"'/traffic?auth='"$METRICS_TOKEN"'\"",           "title": "'"$TITLE"'",
           "constant_node_data_obj": {
               "node_sni": "'"$DOMAIN"'",
               "node_proto_port": '"$INTERNAL_PORT"'
           }
         }')

if [ "$HTTP_CODE" -ne 200 ]; then
    log "\033[31mОшибка регистрации (HTTP $HTTP_CODE): $(cat "$REG_RESPONSE")\033[0m"
    rm -f "$REG_RESPONSE"
    exit 1
fi

NODE_PROTO_ID=$(jq -r '.node_proto_id' "$REG_RESPONSE")
TITLE=$(jq -r '.title' "$REG_RESPONSE")
rm -f "$REG_RESPONSE"

log "Назначен NODE_PROTO_ID: $NODE_PROTO_ID"

CONFIG_PATH="$CONFIG_DIR/hy2-tls-salamander-${NODE_PROTO_ID}.yaml" # конфиги не должны совпасть

# Генерация YAML конфига нативного Hysteria 2
cat <<EOF > "$CONFIG_PATH"
trafficStats:
  listen: 127.0.0.1:$METRICS_PORT
  secret: "$METRICS_TOKEN"

listen: :$INTERNAL_PORT

tls:
  cert: $CERT_PATH
  key: $KEY_PATH

obfs:
  type: salamander
  salamander:
    password: $OBFS_PASS

bandwidth:
  up: 100 mbps
  down: 100 mbps

masquerade:
  type: proxy
  proxy:
    url: https://microsoft.com
    rewriteHost: true
EOF

# Создание systemd сервиса
SERVICE_NAME="reinar-hy2-${NODE_PROTO_ID}"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Hysteria 2 TLS Salamander Node (PROTO_ID: ${PROTO_ID})
After=network.target

[Service]
User=root
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ExecStart=$HYSTERIA_BIN server -c $CONFIG_PATH
Restart=on-failure
RestartPreventExitStatus=23
LimitNPROC=10000
LimitNOFILE=1000000

[Install]
WantedBy=multi-user.target
EOF

log "2. Запуск юнита $SERVICE_NAME..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >&2
systemctl restart "$SERVICE_NAME" >&2

sleep 1

if ! systemctl is-active --quiet "$SERVICE_NAME"; then
    log "\033[31mСервис $SERVICE_NAME не смог запуститься! Откат...\033[0m"
    systemctl stop "$SERVICE_NAME" || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$CONFIG_PATH" "$SERVICE_PATH"
    systemctl daemon-reload

    # Оповещаем панель о фейле
    curl -s -X POST "$PANEL_CONFIRM_URL" -H "Content-Type: application/json" \
         -d '{"node_proto_id": '"$NODE_PROTO_ID"', "status": 3}' >/dev/null || true
    exit 1
fi

# Хук на авто-рестарт виртуальной ноды при обновлении сертификата acme
if ! grep -Fxq "$SERVICE_NAME" "$SERVICES_LIST" 2>/dev/null; then
        echo "$SERVICE_NAME" >> "$SERVICES_LIST"
fi
# 6. Финализация статуса в панели
curl -s -X POST "$PANEL_CONFIRM_URL" -H "Content-Type: application/json" \
     -d '{
        "node_proto_id": '"$NODE_PROTO_ID"',
        "status": 2,
        "service_name": "'$SERVICE_NAME'",
        "reload_core_command": "systemctl restart '"$SERVICE_NAME"'",
        "config_path": "'"$CONFIG_PATH"'",
     }' >/dev/null

log "=================================================="
log "✓ Виртуальная нода успешно создана!"
log "Node Proto ID: $NODE_PROTO_ID"
log "Config Path: $CONFIG_PATH"
log "Title: $TITLE"
log "Основной Порт: $INTERNAL_PORT | SNI Domain: $DOMAIN"
log "=================================================="

# 7. Возврат результата в stdout (JSON) для вызывающего скрипта
jq -n \
  --arg node_proto_id "$NODE_PROTO_ID" \
  --arg service_name "$SERVICE_NAME" \
  '{node_proto_id: $node_proto_id, service_name: $service_name}'

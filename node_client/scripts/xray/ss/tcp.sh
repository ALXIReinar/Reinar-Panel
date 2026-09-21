#!/bin/bash

METHOD_CHOICE=${1}

log() { echo -e "$1" >&2; }

if [ -z "$NODE_ID" ] || [ -z "$PROTO_ID" ]; then
    log "\033[31mОшибка: Укажите NODE_ID и PROTO_ID!\033[0m"
    exit 1
fi

if [ -z "$METHOD_CHOICE" ]; then
    log "Выберите метод шифрования SS-2022:"
    log "1 - 2022-blake3-aes-128-gcm (быстрый, легкий)"
    log "2 - 2022-blake3-aes-256-gcm (максимальная защита)"
    log "3 - 2022-blake3-chacha20-poly1305 (лучше для мобильных без AES-инструкций)"
    read -p "Введите цифру (1-3) [по умолчанию 1]: " METHOD_CHOICE
fi

if [ -z "$TITLE" ]; then
    log "Название для виртуальной ноды не указано. Будет использовано составное"
    TITLE="Vnode_PrId-'$PROTO_ID'_NId-'$NODE_ID'"
fi

# Маппинг цифры в параметры
case "$METHOD_CHOICE" in
    2)
        SS_METHOD="2022-blake3-aes-256-gcm"
        KEY_LENGTH=32
        ;;
    3)
        SS_METHOD="2022-blake3-chacha20-poly1305"
        KEY_LENGTH=32
        ;;
    *)
        # Дефолтный fallback на 128-gcm
        SS_METHOD="2022-blake3-aes-128-gcm"
        KEY_LENGTH=16
        ;;
esac

XRAY_BIN="/usr/local/bin/xray"
CONFIG_DIR="/etc/reinar/configs/xray/ss"
PANEL_CALLBACK_URL="http://10.0.0.1:$ADMIN_PANEL_PORT/api/v1/server/nodes/protocols/register"
PANEL_CONFIRM_URL="http://10.0.0.1:$ADMIN_PANEL_PORT/api/v1/server/nodes/protocols/confirm"

mkdir -p "$CONFIG_DIR"

find_free_port() {
  local port=$1
  while ss -lnt | awk '{print $4}' | grep -q ":$port$"; do
    port=$((port + 1))
  done
  echo $port
}

API_PORT=$(find_free_port 10085)
INBOUND_PORT=$(find_free_port 8388)
SERVER_PSK=$(openssl rand -base64 $KEY_LENGTH)


log "Выделен внутренний порт для Sing-box: $INBOUND_PORT"


log "1. Регистрация ноды в панели и получение node_proto_id..."

REG_RESPONSE=$(mktemp)
HTTP_CODE=$(curl -s -w "%{http_code}" -o "$REG_RESPONSE" -X POST "$PANEL_CALLBACK_URL" \
     -H "Content-Type: application/json" \
     -d '{
           "proto_id": '"$PROTO_ID"',
           "node_id": '"$NODE_ID"',
           "proto_port": '"$INBOUND_PORT"',
           "metrics_port": '"$API_PORT"',
           "title": "'"$TITLE"'",
           "constant_node_data_obj": {
              "node_method": "'$SS_METHOD'"
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

CONFIG_PATH="$CONFIG_DIR/ss-tcp-${NODE_PROTO_ID}.json"
cat <<EOF > "$CONFIG_PATH"
{
  "log": { "loglevel": "warning" },
  "api": {
    "services": ["HandlerService", "LoggerService", "StatsService"],
    "tag": "api"
  },
  "stats": {},
  "policy": {
    "levels": { "0": { "statsUserUplink": true, "statsUserDownlink": true } },
    "system": { "statsInboundUplink": true, "statsInboundDownlink": true }
  },
  "inbounds": [
    {
      "listen": "0.0.0.0",
      "port": $INBOUND_PORT,
      "protocol": "shadowsocks",
      "settings": {
        "method": "$SS_METHOD",
        "password": "$SERVER_PSK",
        "network": "tcp,udp",
        "clients": []
      },
      "tag": "ss-inbound"
    },
    {
      "listen": "127.0.0.1",
      "port": $API_PORT,
      "protocol": "dokodemo-door",
      "settings": { "address": "127.0.0.1" },
      "tag": "api"
    }
  ],
  "outbounds": [
    { "protocol": "freedom", "tag": "direct" },
    { "protocol": "blackhole", "tag": "block" }
  ],
  "routing": {
    "rules": [
      { "inboundTag": ["api"], "outboundTag": "api_out", "type": "field" },
      { "ip": ["geoip:private"], "outboundTag": "block", "type": "field" }
    ]
  }
}
EOF

SERVICE_NAME="reinar-ss-${NODE_PROTO_ID}"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Xray Shadowsocks-2022 TCP (NODE_PROTO_ID: ${NODE_PROTO_ID})
After=network.target nss-lookup.target

[Service]
User=root
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ExecStart=$XRAY_BIN run -config $CONFIG_PATH
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
log "Основной Порт: $INBOUND_PORT"
log "=================================================="

# 7. Возврат результата в stdout (JSON) для вызывающего скрипта
jq -n \
  --arg node_proto_id "$NODE_PROTO_ID" \
  --arg service_name "$SERVICE_NAME" \
  '{node_proto_id: $node_proto_id, service_name: $service_name}'
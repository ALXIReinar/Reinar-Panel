#!/bin/bash

CERT_PATH=$1
KEY_PATH=$2
DOMAIN=$3

log() { echo -e "$1" >&2; }

if [ -z "$NODE_ID" ] || [ -z "$PROTO_ID" ]; then
    log "\033[31mОшибка: Укажите NODE_ID и PROTO_ID в переменных окружения!\033[0m"
    exit 1
fi

if [ -z "$CERT_PATH" ] || [ -z "$KEY_PATH" ] || [ -z "$DOMAIN" ]; then
    log "Ошибка: Не указан TMP_ID!"
    log "Использование: bash ss-ws-install.sh <METHOD_CHOICE> cert_path> <key_path> <domain>"
    exit 1
fi

if [ -z "$TITLE" ]; then
    log "Название для виртуальной ноды не указано. Будет использовано составное"
    TITLE="Vnode_PrId-'$PROTO_ID'_NId-'$NODE_ID'"
fi

SINGBOX_BIN="/usr/local/bin/sing-box"
CONFIG_DIR="/etc/reinar/configs/sing-box/wh_list"
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

INTERNAL_PORT=$(find_free_port 443)
METRICS_PORT=$(find_free_port 10085)
EXIT_UUID=$(uuidgen)

log "Выделен внутренний порт для Sing-box: $INTERNAL_PORT"

log "1. Регистрация ноды в панели и получение node_proto_id..."

REG_RESPONSE=$(mktemp)
HTTP_CODE=$(curl -s -w "%{http_code}" -o "$REG_RESPONSE" -X POST "$PANEL_CALLBACK_URL" \
     -H "Content-Type: application/json" \
     -d '{
           "proto_id": '"$PROTO_ID"',
           "node_id": '"$NODE_ID"',
           "proto_port": '"$INTERNAL_PORT"',
           "metrics_port": '"$METRICS_PORT"',
           "title": "'"$TITLE"'"
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

CONFIG_PATH="$CONFIG_DIR/vmess-tls-tcp-exit-${NODE_PROTO_ID}.json"
cat <<EOF > "$CONFIG_PATH"
{
  "log": {
      "level": "info",
      "timestamp": true
  },
  "experimental": {
    "v2ray_api": {
      "listen": "127.0.0.1:$METRICS_PORT",
      "stats": {
        "enabled": true,
        "inbounds": [
          "hysteria-in"
        ],
        "users": []
      }
    }
  },
  "inbounds": [
    {
      "type": "vmess",
      "tag": "vmess-sys-in",
      "listen": "::",
      "listen_port": $INTERNAL_PORT,
      "users": [
          "name": "ru-entry-node",
          "uuid": "$EXIT_UUID",
          "alterId": 0
      ],
      "tls": {
        "enabled": true,
        "server_name": "$DOMAIN",
        "certificate_path": "$CERT_PATH",
        "key_path": "$KEY_PATH"
      }
    }
  ],
  "outbounds": [
    {
      "type": "direct",
      "tag": "direct"
    }
  ]
}
EOF

# Создание systemd сервиса
SERVICE_NAME="reinar-vmess-${NODE_PROTO_ID}"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Sing-box Vmess TLS TCP Exit Node (NODE_PROTO_ID: ${NODE_PROTO_ID})
After=network.target nss-lookup.target

[Service]
User=root
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ExecStart=$SINGBOX_BIN run -c $CONFIG_PATH
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
        "reload_core_command": "systemctl restart '"$SERVICE_NAME"'",
        "config_path": "'"$CONFIG_PATH"'",
     }' >/dev/null

log "=================================================="
log "Sing-box Vmess TLS TCP node в качестве EXIT ноды развернута!"
log "Node Proto ID: $NODE_PROTO_ID"
log "Config Path: $CONFIG_PATH"
log "Порт:  $INTERNAL_PORT"
log "- UUID: $EXIT_UUID"
log "- EXIT_DOMAIN: $DOMAIN"
log "=================================================="

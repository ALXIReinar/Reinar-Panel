#!/bin/bash

CERT_PATH=$1
KEY_PATH=$2
DOMAIN=$3 # В нативном сервере hy2 не указывается явно в конфиге, берется из сертификата

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
SINGBOX_BIN="/usr/local/bin/sing-box"
CONFIG_DIR="/etc/reinar/configs/sing-box/hy2"
PANEL_CALLBACK_URL="http://10.0.0.1:$ADMIN_PANEL_PORT/api/v1/server/nodes/protocols/register"
PANEL_CONFIRM_URL="http://10.0.0.1:$ADMIN_PANEL_PORT/api/v1/server/nodes/protocols/confirm"
IPTABLES_BIN=$(command -v iptables)

mkdir -p "$CONFIG_DIR"

# Функция поиска свободного одиночного порта
find_free_port() {
    local port=$1
    while ss -lntu | awk '{print $4}' | grep -q ":$port$"; do
        port=$((port + 1))
    done
    echo $port
}

# Функция поиска свободного диапазона портов (размером 100 портов)
find_free_port_range() {
    local range_size=100
    local start_port=20000
    local max_port=60000

    while [ $start_port -le $max_port ]; do
        local end_port=$((start_port + range_size - 1))
        local busy=0

        for p in $(seq $start_port $end_port); do
            if ss -lntu | awk '{print $4}' | grep -q ":$p$"; then
                busy=1
                break
            fi
        done

        if [ $busy -eq 0 ]; then
            echo "$start_port $end_port"
            return 0
        fi

        start_port=$((start_port + range_size))
    done

    # Fallback, если всё занято
    echo "20000 20099"
}

# Ищем свободный внутренний порт для сингбокса
INTERNAL_PORT=$(find_free_port 8443)
METRICS_PORT=$(find_free_port 10085)

# Ищем свободный диапазон для хоппинга
read RANGE_START RANGE_END <<< $(find_free_port_range)

log "Выделен внутренний порт для Sing-box: $INTERNAL_PORT"
log "Выделен диапазон портов для Port Hopping: ${RANGE_START}-${RANGE_END}"


log "1. Регистрация ноды в панели и получение node_proto_id..."
REG_RESPONSE=$(mktemp)
HTTP_CODE=$(curl -s -w "%{http_code}" -o "$REG_RESPONSE" -X POST "$PANEL_CALLBACK_URL" \
     -H "Content-Type: application/json" \
     -d '{
           "proto_id": "'"$PROTO_ID"'",
           "node_id": "'"$NODE_ID"'",
           "config_path": "'"$CONFIG_PATH"'",
           "proto_port": '"$INTERNAL_PORT"',
           "metrics_port": '"$METRICS_PORT"',
           "constant_node_data_obj": {
               "node_hop_start": '"$RANGE_START"',
               "node_hop_end": '"$RANGE_END"'
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

# 2. Формирование путей с новым ID
SERVICE_NAME="reinar-hy2-${NODE_PROTO_ID}"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
CONFIG_PATH="$CONFIG_DIR/hy2-tls-salamander-hopping-${NODE_PROTO_ID}.json" # конфиги не должны совпасть

# Генерация конфига Sing-box
cat <<EOF > "$CONFIG_PATH"
{
  "log": {
    "level": "warn"
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
      "type": "hysteria2",
      "tag": "hysteria-in",
      "listen": "::",
      "listen_port": $INTERNAL_PORT,
      "users": [],
      "tls": {
        "enabled": true,
        "server_name": "$DOMAIN",
        "certificate_path": "$CERT_PATH",
        "key_path": "$KEY_PATH",
        "alpn": ["h3"]
      },
      "obfs": {
        "type": "salamander",
        "password": "$OBFS_PASS"
      },
      "up_mbps": 100,
      "down_mbps": 100
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

cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Sing-box Hysteria2 Salamander Hopping Node (NODE_PROTO_ID: ${NODE_PROTO_ID})
After=network.target nss-lookup.target

[Service]
User=root
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
NoNewPrivileges=true
# Добавляем правило PostUp (выполняется от полного root благодаря '+')
ExecStartPre=+${IPTABLES_BIN} -t nat -A PREROUTING -p udp --dport ${RANGE_START}:${RANGE_END} -j REDIRECT --to-ports ${INTERNAL_PORT}

ExecStart=$SINGBOX_BIN run -c $CONFIG_PATH

# Удаляем правило PostDown (знак '-' игнорирует ошибки, если правила нет)
ExecStopPost=+-${IPTABLES_BIN} -t nat -D PREROUTING -p udp --dport ${RANGE_START}:${RANGE_END} -j REDIRECT --to-ports ${INTERNAL_PORT}

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
         -d '{"node_proto_id": "'"$NODE_PROTO_ID"'", "status": 3}' >/dev/null || true
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
        "reload_core_command": "systemctl restart '"$SERVICE_NAME"'",
        "config_path": "'"$CONFIG_PATH"'",
     }' >/dev/null

log "=================================================="
log "✓ Виртуальная нода успешно создана!"
log "Node Proto ID: $NODE_PROTO_ID"
log "Config Path: $CONFIG_PATH"
log "Title: $TITLE"
log "Основной Порт: $INTERNAL_PORT | Port Hopping Range: $RANGE_START-$RANGE_END"
log "=================================================="


# 7. Возврат результата в stdout (JSON) для вызывающего скрипта
jq -n \
  --arg node_proto_id "$NODE_PROTO_ID" \
  --arg service_name "$SERVICE_NAME" \
  '{node_proto_id: $node_proto_id, service_name: $service_name}'

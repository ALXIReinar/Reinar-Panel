#!/bin/bash

# Адреса самого сервера внутри туннеля (с маской). Передаются из панели.
# Пример: 10.1.0.1/16
IP_ADDR=$1
# Пример: fd00:1::1/64
IP_VERSION=$2

log() { echo -e "$1" >&2; }

if [ -z "$NODE_ID" ] || [ -z "$PROTO_ID" ]; then
    log "\033[31mОшибка: Укажите NODE_ID и PROTO_ID в переменных окружения!\033[0m"
    exit 1
fi

if [ -z "$IP_ADDR" ] || [ -z "$IP_VERSION" ]; then
    log "Ошибка: Необходимы параметры IP_ADDR, IP_VERSION !"
    log "Использование: bash node_client/scripts/sing-box/wg/awg-server-hopping.sh <ip_addr> <ip_version>"
    exit 1
fi

if [[ "$IP_VERSION" != "4" && "$IP_VERSION" != "6" ]]; then
    log "IP_VERSION must be 4 or 6"
    exit 1
fi

# Используем кастомный бинарник!
SINGBOX_BIN="/usr/local/bin/sing-box"
CONFIG_DIR="/etc/reinar/configs/sing-box/wg"
PANEL_CALLBACK_URL="http://10.0.0.1:$ADMIN_PANEL_PORT/api/v1/server/nodes/protocols/register"
PANEL_CONFIRM_URL="http://10.0.0.1:$ADMIN_PANEL_PORT/api/v1/server/nodes/protocols/confirm"
IPTABLES_BIN=$(command -v iptables)
IP6TABLES_BIN=$(command -v ip6tables)

mkdir -p "$CONFIG_DIR"


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

# Функция поиска свободного порта
find_free_port() {
    local port=$1
    while ss -lntu | awk '{print $4}' | grep -q ":$port$"; do
        port=$((port + 1))
    done
    echo $port
}

WG_PORT=$(find_free_port 51820)
METRICS_PORT=$(find_free_port 10085)

log "Выделен порт для WireGuard: $WG_PORT"
log "Выделен порт для Метрик: $METRICS_PORT"

# --- ГЕНЕРАЦИЯ КЛЮЧЕЙ СЕРВЕРА ---
# sing-box выдает вывод вида:
# PrivateKey: <base64>
# PublicKey: <base64>
WG_KEYS=$($SINGBOX_BIN generate wg-keypair)
WG_PRIVATE_KEY=$(echo "$WG_KEYS" | grep PrivateKey | awk '{print $2}')
WG_PUBLIC_KEY=$(echo "$WG_KEYS" | grep PublicKey | awk '{print $2}')
NODE_HASH_SALT=$(openssl rand -base64 12)

# Ищем свободный диапазон для хоппинга
# shellcheck disable=SC2046
# shellcheck disable=SC2162
read RANGE_START RANGE_END <<< $(find_free_port_range)

log "Выделен порт для AmneziaWG: $WG_PORT"
log "Выделен диапазон портов для Port Hopping: ${RANGE_START}-${RANGE_END}"

REG_RESPONSE=$(mktemp)
HTTP_CODE=$(curl -s -w "%{http_code}" -o "$REG_RESPONSE" -X POST "$PANEL_CALLBACK_URL" \
     -H "Content-Type: application/json" \
     -d '{
           "proto_id": '"$PROTO_ID"',
           "node_id": '"$NODE_ID"',
           "proto_port": '"$WG_PORT"',
           "metrics_port": '"$METRICS_PORT"',
           "title": "'"$TITLE"'",
           "constant_node_data_obj": {
               "node_ipv'"$IP_VERSION"'_subnet": "'"$IP_ADDR"'",
               "node_public_key": "'"$WG_PUBLIC_KEY"'",
               "node_hop_start": '"$RANGE_START"',
               "node_hop_end": '"$RANGE_END"',
               "node_hash_salt": '"$NODE_HASH_SALT"'
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


# shellcheck disable=SC1073
# shellcheck disable=SC1072
# shellcheck disable=SC1009
if [ "$IP_VERSION" --eq 4]; then
  SYSTEMD_PRE_START="+${IPTABLES_BIN} -t nat -A PREROUTING -p udp --dport ${RANGE_START}:${RANGE_END} -j REDIRECT --to-ports ${WG_PORT}"
  SYSTEMD_POST_DOWN="+-${IPTABLES_BIN} -t nat -D PREROUTING -p udp --dport ${RANGE_START}:${RANGE_END} -j REDIRECT --to-ports ${WG_PORT}"
fi

if [ "$IP_VERSION" --eq 6]; then
  SYSTEMD_PRE_START="+${IP6TABLES_BIN} -t nat -A PREROUTING -p udp --dport ${RANGE_START}:${RANGE_END} -j REDIRECT --to-ports ${WG_PORT}"
  SYSTEMD_POST_DOWN="+-${IP6TABLES_BIN} -t nat -D PREROUTING -p udp --dport ${RANGE_START}:${RANGE_END} -j REDIRECT --to-ports ${WG_PORT}"
fi

# Генерация конфига Sing-box
CONFIG_PATH="$CONFIG_DIR/wg-hopping-${NODE_PROTO_ID}.json" # конфиги не должны совпасть
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
          "wg-in"
        ],
        "users": []
      }
    }
  },
  "inbounds": [
    {
      "type": "wireguard",
      "tag": "wg-in",
      "listen": "::",
      "listen_port": $WG_PORT,
      "system": false,
      "local_address": [
        "$IP_ADDR"
      ],
      "private_key": "$WG_PRIVATE_KEY",
      "peers": []
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
SERVICE_NAME="reinar-wg-${NODE_PROTO_ID}"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Sing-box WireGuard Node Hopping (NODE_PROTO_ID: ${NODE_PROTO_ID})
After=network.target nss-lookup.target

[Service]
User=root
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
NoNewPrivileges=true
ExecStart=$SINGBOX_BIN run -c $CONFIG_PATH
ExecStartPre=${SYSTEMD_PRE_START}
ExecStopPost=${SYSTEMD_POST_DOWN}
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
log "WireGuard развернут"
log "Node Proto ID: $NODE_PROTO_ID"
log "Config Path: $CONFIG_PATH"
log "Title: $TITLE"
log "Основной Порт: $WG_PORT | Port Hopping Range: ${RANGE_START}-${RANGE_END}"
log "Public Key: $WG_PUBLIC_KEY"
log "=================================================="


# 7. Возврат результата в stdout (JSON) для вызывающего скрипта
jq -n \
  --arg node_proto_id "$NODE_PROTO_ID" \
  --arg service_name "$SERVICE_NAME" \
  '{node_proto_id: $node_proto_id, service_name: $service_name}'

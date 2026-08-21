#!/bin/bash

TMP_ID=$1
CERT_PATH=$2
KEY_PATH=$3
SNI_DOMAIN=$4

if [ -z "$TMP_ID" ] || [ -z "$CERT_PATH" ] || [ -z "$KEY_PATH" ] || [ -z "$SNI_DOMAIN" ]; then
    echo "Ошибка: Необходимы параметры TMP_ID, CERT_PATH, KEY_PATH и SNI_DOMAIN!"
    echo "Использование: bash sing-box-hy2-hopping-install.sh <tmp_id> <cert_path> <key_path> <sni_domain>"
    exit 1
fi

SINGBOX_BIN="/usr/local/bin/sing-box"
CONFIG_DIR="/etc/sing-box/configs"
CONFIG_PATH="$CONFIG_DIR/${TMP_ID}.json"
PANEL_CALLBACK_URL="http://10.0.0.1/api/node/callback"

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
# shellcheck disable=SC2046
# shellcheck disable=SC2162
read RANGE_START RANGE_END <<< $(find_free_port_range)

echo "Выделен внутренний порт для Sing-box: $INTERNAL_PORT"
echo "Выделен диапазон портов для Port Hopping: ${RANGE_START}-${RANGE_END}"

# Включаем IP Forwarding и настраиваем NAT PREROUTING для UDP хоппинга
iptables -t nat -A PREROUTING -p udp --dport ${RANGE_START}:${RANGE_END} -j REDIRECT --to-ports ${INTERNAL_PORT}

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
        "server_name": "$SNI_DOMAIN",
        "certificate_path": "$CERT_PATH",
        "key_path": "$KEY_PATH",
        "alpn": ["h3"]
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

# Создание systemd сервиса
SERVICE_PATH="/etc/systemd/system/sing-box-${TMP_ID}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Sing-box Hysteria2 Hopping Node (TMP_ID: ${TMP_ID})
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

systemctl daemon-reload
systemctl enable "sing-box-${TMP_ID}"
systemctl restart "sing-box-${TMP_ID}"

# Отправка callback-запроса в панель
curl -s -X POST "$PANEL_CALLBACK_URL" \
     -H "Content-Type: application/json" \
     -d '{
           "tmp_id": "'"$TMP_ID"'",
           "config_path": "'"$CONFIG_PATH"'",
           "internal_port": '$INTERNAL_PORT',
           "status": "installed",
           "node_type": "singbox_hysteria2_hopping",
           "custom_fields": {
               "hop_start": '$RANGE_START',
               "hop_end": '$RANGE_END'
           }
         }'

echo "=================================================="
echo "Sing-box Hysteria2 с Port Hopping развернута."
echo "Диапазон прыжков: ${RANGE_START}-${RANGE_END}"
echo "Внутренний порт:  $INTERNAL_PORT"
echo "=================================================="
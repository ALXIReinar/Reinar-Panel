#!/bin/bash

TMP_ID=$1
CERT_PATH=$2
KEY_PATH=$3
SNI_DOMAIN=$4 # В нативном сервере hy2 не указывается явно в конфиге, берется из сертификата

if [ -z "$TMP_ID" ] || [ -z "$CERT_PATH" ] || [ -z "$KEY_PATH" ] || [ -z "$SNI_DOMAIN" ]; then
    echo "Ошибка: Необходимы параметры TMP_ID, CERT_PATH, KEY_PATH и SNI_DOMAIN!"
    echo "Использование: bash hysteria2-hopping-install.sh <tmp_id> <cert_path> <key_path> <sni_domain>"
    exit 1
fi

HYSTERIA_BIN="/usr/local/bin/hysteria"
CONFIG_DIR="/etc/hysteria/configs"
CONFIG_PATH="$CONFIG_DIR/${TMP_ID}.yaml"
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

# Ищем свободный внутренний порт для Hysteria
INTERNAL_PORT=$(find_free_port 8443)
METRICS_PORT=$(find_free_port 10085)
METRICS_TOKEN=$(openssl rand -hex 8)

# Ищем свободный диапазон для хоппинга
read RANGE_START RANGE_END <<< $(find_free_port_range)

echo "Выделен внутренний порт для Hysteria: $INTERNAL_PORT"
echo "Выделен диапазон портов для Port Hopping: ${RANGE_START}-${RANGE_END}"

# Включаем IP Forwarding и настраиваем NAT PREROUTING для UDP хоппинга
sysctl -w net.ipv4.ip_forward=1 > /dev/null
iptables -t nat -A PREROUTING -p udp --dport ${RANGE_START}:${RANGE_END} -j REDIRECT --to-ports ${INTERNAL_PORT}

# Генерация YAML конфига нативного Hysteria 2
cat <<EOF > "$CONFIG_PATH"
trafficStats:
  listen: 127.0.0.1:$METRICS_PORT
  secret: "$METRICS_TOKEN"

listen: :$INTERNAL_PORT

tls:
  cert: $CERT_PATH
  key: $KEY_PATH

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
SERVICE_PATH="/etc/systemd/system/hysteria-${TMP_ID}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Hysteria 2 TLS Hopping Node (TMP_ID: ${TMP_ID})
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

systemctl daemon-reload
systemctl enable "hysteria-${TMP_ID}"
systemctl restart "hysteria-${TMP_ID}"

# Отправка callback-запроса в панель
curl -s -X POST "$PANEL_CALLBACK_URL" \
     -H "Content-Type: application/json" \
     -d '{
           "tmp_id": "'"$TMP_ID"'",
           "config_path": "'"$CONFIG_PATH"'",
           "internal_port": '"$INTERNAL_PORT"',
           "metrics_port": '"$METRICS_PORT"',
           "metrics_command" : "curl \"http://127.0.0.1:'"$METRICS_PORT"'/traffic?auth='"$METRICS_TOKEN"'\"",
           "status": "installed",
           "node_type": "native_hysteria2_hopping",
           "constant_node_data_obj": {
               "node_hop_start": '"$RANGE_START"',
               "node_hop_end": '"$RANGE_END"',
               "node_sni": "'"$SNI_DOMAIN"'"
           }
         }'

echo "=================================================="
echo "Native Hysteria2 Salamander с Port Hopping развернута."
echo "Диапазон прыжков: ${RANGE_START}-${RANGE_END}"
echo "Внутренний порт:  $INTERNAL_PORT"
echo "=================================================="
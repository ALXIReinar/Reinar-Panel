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

OBFS_PASS=$(openssl rand -hex 8)
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

# Ищем свободный внутренний порт для Hysteria
INTERNAL_PORT=$(find_free_port 8443)
METRICS_PORT=$(find_free_port 10085)
METRICS_TOKEN=$(openssl rand -hex 8)

echo "Выделен внутренний порт для Hysteria: $INTERNAL_PORT"


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
SERVICE_PATH="/etc/systemd/system/hysteria-${TMP_ID}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Hysteria 2 TLS Salamander Node (TMP_ID: ${TMP_ID})
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
           "node_type": "native_hysteria2_tls_salamander_hopping",
           "constant_node_data_obj": {
               "node_sni": "'"$SNI_DOMAIN"'",
               "proto_port": '"$INTERNAL_PORT"'
           }
         }'

echo "=================================================="
echo "Native Hysteria2 Salamander с Port Hopping развернута."
echo "Внутренний порт:  $INTERNAL_PORT"
echo "=================================================="
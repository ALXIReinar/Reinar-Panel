#!/bin/bash

TMP_ID=$1
CERT_PATH=$2
KEY_PATH=$3
DOMAIN=$4


if [ -z "$TMP_ID" ] || [ -z "$CERT_PATH" ] || [ -z "$KEY_PATH" ] || [ -z "$DOMAIN" ]; then
    echo "Ошибка: Не указан TMP_ID!"
    echo "Использование: bash ss-ws-install.sh <tmp_id> <cert_path> <key_path> <domain>"
    exit 1
fi

SINGBOX_BIN="/usr/local/bin/sing-box"
CONFIG_DIR="/etc/sing-box/configs"
CONFIG_PATH="$CONFIG_DIR/${TMP_ID}.json"
PANEL_CALLBACK_URL="http://10.0.0.1/api/node/callback"

mkdir -p "$CONFIG_DIR"

find_free_port() {
  local port=$1
  while ss -lnt | awk '{print $4}' | grep -q ":$port$"; do
    port=$((port + 1))
  done
  echo $port
}

INTERNAL_PORT=$(find_free_port 443)
EXIT_UUID=$(uuidgen)

cat <<EOF > "$CONFIG_PATH"
{
  "log": {
      "level": "info",
      "timestamp": true
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
SERVICE_PATH="/etc/systemd/system/sing-box-${TMP_ID}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Sing-box Vmess TLS TCP Exit Node (TMP_ID: ${TMP_ID})
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

curl -s -X POST "$PANEL_CALLBACK_URL" \
     -H "Content-Type: application/json" \
     -d '{
           "tmp_id": "'"$TMP_ID"'",
           "config_path": "'"$CONFIG_PATH"'",
           "api_port": '"$API_POPT"',
           "inbound_port": '"$INBOUND_PORT"',
           "status": "installed",
           "node_type": "vmess_tls_tcp"
         }'

echo "=================================================="
echo "Sing-box Vmess TLS TCP node в качестве EXIT ноды развернута!"
echo "Порт:  $INTERNAL_PORT"
echo "Exit нода $TMP_ID установлена. Данные для подключения Entry Ноды"
echo "- UUID: $EXIT_UUID"
echo "- EXIT_DOMAIN: $DOMAIN"
echo "=================================================="

#!/bin/bash

TMP_ID=$1
CERT_PATH=$2
KEY_PATH=$3
SNI_DOMAIN=$4

if [ -z "$TMP_ID" ] || [ -z "$CERT_PATH" ] || [ -z "$KEY_PATH" ] || [ -z "$SNI_DOMAIN" ]; then
    echo "Ошибка: Необходимы параметры TMP_ID, CERT_PATH, KEY_PATH и SNI_DOMAIN!"
    echo "Использование: bash xray-hysteria2-install.sh <tmp_id> <cert_path> <key_path> <sni_domain>"
    exit 1
fi

XRAY_BIN="/usr/local/bin/xray"
CONFIG_DIR="/etc/xray/configs"
CONFIG_PATH="$CONFIG_DIR/${TMP_ID}.json"
PANEL_CALLBACK_URL="http://10.0.0.1/api/node/callback"

mkdir -p "$CONFIG_DIR"

find_free_port() {
    local port=$1
    # Для Hysteria нам нужен свободный UDP порт, но проверяем и TCP и UDP
    while ss -lntu | awk '{print $4}' | grep -q ":$port$"; do
        port=$((port + 1))
    done
    echo $port
}

API_PORT=$(find_free_port 10085)
INBOUND_PORT=$(find_free_port 443) # Желательно 443 для обхода DPI, но скрипт найдет любой

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
      "protocol": "hysteria",
      "settings": {
        "version": 2,
        "users": []
      },
      "streamSettings": {
        "network": "hysteria",
        "security": "tls",
        "tlsSettings": {
          "alpn": ["h3"],
          "serverName": "$SNI_DOMAIN",
          "certificates": [
            {
              "certificateFile": "$CERT_PATH",
              "keyFile": "$KEY_PATH"
            }
          ]
        },
        "hysteriaSettings": {
          "version": 2,
          "masquerade": {
            "type": "404"
          },
          "udpIdleTimeout": 600
        }
      },
      "tag": "hysteria-inbound"
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
    { "protocol": "blackhole", "tag": "block" },
    { "protocol": "none", "tag": "api_out" }
  ],
  "routing": {
    "rules": [
      { "inboundTag": ["api"], "outboundTag": "api_out", "type": "field" },
      { "ip": ["geoip:private"], "outboundTag": "block", "type": "field" }
    ]
  }
}
EOF

SERVICE_PATH="/etc/systemd/system/xray-${TMP_ID}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Xray Hysteria2 Node (TMP_ID: ${TMP_ID})
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

systemctl daemon-reload
systemctl enable "xray-${TMP_ID}"
systemctl restart "xray-${TMP_ID}"

curl -s -X POST "$PANEL_CALLBACK_URL" \
     -H "Content-Type: application/json" \
     -d '{
           "tmp_id": "'"$TMP_ID"'",
           "config_path": "'"$CONFIG_PATH"'",
           "api_port": '$API_PORT',
           "inbound_port": '$INBOUND_PORT',
           "status": "installed",
           "node_type": "hysteria2"
         }'

echo "Hysteria2 нода $TMP_ID успешно установлена."
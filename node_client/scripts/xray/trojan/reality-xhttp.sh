#!/bin/bash

TMP_ID=$1
REALITY_SNI=${2:-"microsoft.com"}

if [ -z "$TMP_ID" ]; then
    echo "Ошибка: Не указан TMP_ID!"
    exit 1
fi

XRAY_BIN="/usr/local/bin/xray"
CONFIG_DIR="/etc/xray/configs"
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

API_PORT=$(find_free_port 10085)
INBOUND_PORT=$(find_free_port 443)

# Генерация ключей для REALITY
X25519_KEYPAIR=$($XRAY_BIN x25519)
PRIVATE_KEY=$(echo "$X25519_KEYPAIR" | grep "Private key:" | awk '{print $3}')
PUBLIC_KEY=$(echo "$X25519_KEYPAIR" | grep "Public key:" | awk '{print $3}')
SHORT_ID=$(openssl rand -hex 8)
XHTTP_PATH=$(openssl rand -hex 4)

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
      "protocol": "trojan",
      "settings": {
        "clients": []
      },
      "streamSettings": {
        "network": "xhttp",
        "xhttpSettings": {
          "mode": "auto",
          "path": "/xhttp-$XHTTP_PATH-trojan",
          "host": "$REALITY_SNI"
        },
        "security": "reality",
        "realitySettings": {
          "dest": "$REALITY_SNI:443",
          "serverNames": ["$REALITY_SNI"],
          "privateKey": "$PRIVATE_KEY",
          "shortIds": ["$SHORT_ID"]
        }
      },
      "tag": "trojan-inbound"
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

SERVICE_PATH="/etc/systemd/system/xray-${TMP_ID}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Xray Trojan-REALITY-XHttp Node (TMP_ID: ${TMP_ID})
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
           "node_type": "trojan_reality",
           "custom_fields": {
               "public_key": "'"$PUBLIC_KEY"'"
           }
         }'

echo "Trojan-REALITY-Xhttp нода $TMP_ID успешно установлена."
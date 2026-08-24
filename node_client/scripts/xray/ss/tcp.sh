#!/bin/bash

TMP_ID=$1
METHOD_CHOICE=${2}

if [ -z "$TMP_ID" ]; then
  echo "Error: TMP_ID is missing!"
  echo "Usage: bash ss-2022-install.sh <tmp_id> [method_num]"
  exit 1
fi


if [ -z "$METHOD_CHOICE" ]; then
    echo "Выберите метод шифрования SS-2022:"
    echo "1 - 2022-blake3-aes-128-gcm (быстрый, легкий)"
    echo "2 - 2022-blake3-aes-256-gcm (максимальная защита)"
    echo "3 - 2022-blake3-chacha20-poly1305 (лучше для мобильных без AES-инструкций)"
    read -p "Введите цифру (1-3) [по умолчанию 1]: " METHOD_CHOICE
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
INBOUND_PORT=$(find_free_port 8388)
SERVER_PSK=$(openssl rand -base64 $KEY_LENGTH)



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
Description=Xray Shadowsocks-2022 Exit Node (TMP_ID: ${TMP_ID})
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
           "api_port": '"$API_POPT"',
           "inbound_port": '"$INBOUND_PORT"',
           "status": "installed",
           "node_type": "shadowsocks_2022",
           "constant_node_data_obj": {
              "node_method": "'$SS_METHOD'"
           }
         }'

echo "Shadowsocks-2022 node $TMP_ID installed successfully."
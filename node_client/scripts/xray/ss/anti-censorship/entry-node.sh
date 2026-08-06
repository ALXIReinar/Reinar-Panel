#!/bin/bash

TMP_ID=$1
METHOD=${2:-"2022-blake3-aes-128-gcm"}
EXIT_HOST=$3
EXIT_PORT=$4
EXIT_SERVER_PSK=$5
EXIT_USER_PSK=$6

if [ -z "$TMP_ID" ] || [ -z "$EXIT_HOST" ] || [ -z "$EXIT_PORT" ] || [ -z "$EXIT_SERVER_PSK" ] || [ -z "$EXIT_USER_PSK" ]; then
  echo "Error: Missing required arguments!"
  echo "Usage: bash ss-entry-install.sh <tmp_id> [method] <exit_host> <exit_port> <exit_server_psk> <exit_user_psk>"
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
INBOUND_PORT=$(find_free_port 8388)

# Генерация собственного Server PSK для приёма клиентов
if [[ "$METHOD" == *"128"* ]]; then
  SERVER_PSK=$(openssl rand -base64 16)
else
  SERVER_PSK=$(openssl rand -base64 32)
fi

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
        "method": "$METHOD",
        "password": "$SERVER_PSK",
        "network": "tcp,udp",
        "clients": []
      },
      "tag": "inbound"
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
    {
      "protocol": "shadowsocks",
      "settings": {
        "servers": [
          {
            "address": "$EXIT_HOST",
            "port": $EXIT_PORT,
            "method": "$METHOD",
            "password": "${EXIT_SERVER_PSK}:${EXIT_USER_PSK}"
          }
        ]
      },
      "tag": "freedom_node"
    },
    {
      "protocol": "freedom",
      "tag": "direct"
    },
    {
      "protocol": "blackhole",
      "tag": "block"
    },
    {
      "protocol": "none",
      "tag": "api_out"
    }
  ],
  "routing": {
    "domainStrategy": "IPIfNonMatch",
    "rules": [
      {
        "type": "field",
        "inboundTag": ["api"],
        "outboundTag": "api_out"
      },
      {
        "type": "field",
        "ip": ["geoip:private"],
        "outboundTag": "block"
      },
      {
        "type": "field",
        "protocol": ["bittorrent"],
        "outboundTag": "block"
      },
      {
        "type": "field",
        "domain": ["geosite:category-ru", "domain:ru", "domain:su", "domain:rf"],
        "outboundTag": "direct"
      },
      {
        "type": "field",
        "ip": ["geoip:ru"],
        "outboundTag": "direct"
      },
      {
        "type": "field",
        "network": "tcp,udp",
        "outboundTag": "freedom_node"
      }
    ]
  }
}
EOF

SERVICE_PATH="/etc/systemd/system/xray-${TMP_ID}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Xray Shadowsocks-2022 Entry Node (TMP_ID: ${TMP_ID})
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
           "node_type": "shadowsocks_2022_entry",
           "custom_fields": {
              "method": "'"$METHOD"'",
              "server_psk": "'"$SERVER_PSK"'"
           }
         }'

echo "Shadowsocks-2022 Entry Node $TMP_ID installed successfully."
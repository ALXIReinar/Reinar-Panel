#!/bin/bash

TMP_ID=$1
CERT_PATH=$2
KEY_PATH=$3
DOMAIN=$4

METHOD_CHOICE=${5}


if [ -z "$TMP_ID" ] || [ -z "$CERT_PATH" ] || [ -z "$KEY_PATH" ] || [ -z "$DOMAIN" ]; then
    echo "Ошибка: Не указан TMP_ID!"
    echo "Использование: bash ss-ws-install.sh <tmp_id> <cert_path> <key_path> <domain> [method_choice]"
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

INTERNAL_PORT=$(find_free_port 8388)
METRICS_PORT=$(find_free_port 10085)
SERVER_PSK=$(openssl rand -base64 $KEY_LENGTH)
WS_PATH="/ws-$(openssl rand -hex 4)-ss"


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
          "ss-in"
        ],
        "users": []
      }
    }
  },
  "inbounds": [
    {
      "type": "shadowsocks",
      "tag": "ss-in",
      "listen": "::",
      "listen_port": $INTERNAL_PORT,
      "method": "$SS_METHOD",
      "password": "$SERVER_PSK",
      "users": [],
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
Description=Sing-box Shadowsocks TLS TCP Node (TMP_ID: ${TMP_ID})
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
           "node_type": "shadowsocks_2022",
           "constant_node_data_obj": {
              "node_method": "'$SS_METHOD'"
           }
         }'

echo "Shadowsocks-tcp node $TMP_ID installed successfully."
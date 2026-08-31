#!/bin/bash

TMP_ID=$1
# Адреса самого сервера внутри туннеля (с маской). Передаются из панели.
# Пример: 10.1.0.1/16
IP_ADDR=$2
# Пример: fd00:1::1/64
IP_VERSION=$3

if [ -z "$TMP_ID" ] || [ -z "$IP_ADDR" ] || [ -z "$IP_VERSION" ]; then
    echo "Ошибка: Необходимы параметры TMP_ID, ip_addr, ip_version!"
    echo "Использование: bash sing-box-wg-install.sh <tmp_id> <ip_addr> <ip_version>"
    exit 1
fi

SINGBOX_BIN="/usr/local/bin/sing-box"
CONFIG_DIR="/etc/sing-box/configs"
CONFIG_PATH="$CONFIG_DIR/${TMP_ID}.json"
PANEL_CALLBACK_URL="http://10.0.0.1/api/node/callback"

mkdir -p "$CONFIG_DIR"

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

echo "Выделен порт для WireGuard: $WG_PORT"
echo "Выделен порт для Метрик: $METRICS_PORT"

# --- ГЕНЕРАЦИЯ КЛЮЧЕЙ СЕРВЕРА ---
# sing-box выдает вывод вида:
# PrivateKey: <base64>
# PublicKey: <base64>
WG_KEYS=$($SINGBOX_BIN generate wg-keypair)
WG_PRIVATE_KEY=$(echo "$WG_KEYS" | grep PrivateKey | awk '{print $2}')
WG_PUBLIC_KEY=$(echo "$WG_KEYS" | grep PublicKey | awk '{print $2}')

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
SERVICE_PATH="/etc/systemd/system/sing-box-${TMP_ID}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Sing-box WireGuard Node (TMP_ID: ${TMP_ID})
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

# --- ОТПРАВКА CALLBACK ---
# Важно: Мы отправляем WG_PUBLIC_KEY обратно в панель!
# Панель должна сохранить его в constant_node_data_obj,
# чтобы клиенты знали, к какому серверу подключаться.

curl -s -X POST "$PANEL_CALLBACK_URL" \
     -H "Content-Type: application/json" \
     -d '{
           "tmp_id": "'"$TMP_ID"'",
           "config_path": "'"$CONFIG_PATH"'",
           "proto_port": '"$WG_PORT"',
           "metrics_port": '"$METRICS_PORT"',
           "status": "installed",
           "node_type": "singbox_wg",
           "constant_node_data_obj": {
               "node_ipv'"$IP_VERSION"'_subnet": "'"$IP_ADDR"'",
               "node_public_key": "'"$WG_PUBLIC_KEY"'"
           }
         }'

echo "=================================================="
echo "Sing-box WireGuard развернут."
echo "Порт WG: $WG_PORT | Public Key: $WG_PUBLIC_KEY"
echo "=================================================="
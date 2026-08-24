TMP_ID=$1
CERT_PATH=$2
KEY_PATH=$3
DOMAIN=$4

HTTPUP_PATH=$(openssl rand -hex 4)

if [ -z "$TMP_ID" ] || [ -z "$CERT_PATH" ] || [ -z "$KEY_PATH" ] || [ -z "$DOMAIN" ]; then
    echo "Ошибка: Необходимы параметры TMP_ID, CERT_PATH, KEY_PATH, DOMAIN!"
    echo "Использование: bash trojan-ws-tls-install.sh <tmp_id> <cert_path> <key_path> <domain>"
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

# Ищем свободный внутренний порт для сингбокса
INTERNAL_PORT=$(find_free_port 443)
METRICS_PORT=$(find_free_port 10085)

echo "Выделен внутренний порт для Sing-box: $INTERNAL_PORT"

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
          "trojan-in"
        ],
        "users": []
      }
    }
  },
  "inbounds": [
    {
      "type": "trojan",
      "tag": "trojan-in",
      "listen": "::",
      "listen_port": $INTERNAL_PORT,
      "users": [],
      "transport": {
        "type": "httpupgrade",
        "path": "$HTTPUP_PATH"
      },
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
Description=Sing-box Trojan HttpUpgrade TLS Node (TMP_ID: ${TMP_ID})
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
           "internal_port": '"$INTERNAL_PORT"',
           "status": "installed",
           "node_type": "singbox_hysteria2_hopping",
           "constant_node_data_obj": {
              "sub_link_fp": "chrome"
           }
         }'

echo "=================================================="
echo "Sing-box Hysteria2 Salamander развернута."
echo "Внутренний порт:  $INTERNAL_PORT"
echo "=================================================="
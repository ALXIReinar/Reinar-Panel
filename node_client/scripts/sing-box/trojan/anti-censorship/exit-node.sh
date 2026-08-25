TMP_ID=$1

if [ -z "$TMP_ID" ]; then
    echo "Ошибка: Необходимы параметр TMP_ID!"
    echo "Использование: bash vless-reality-tcp.sh <tmp_id> [sni]"
    exit 1
fi

# Используется кастомное ядро для совместимости
SINGBOX_BIN="/usr/local/bin/sing-box-awg"
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


# Извлекаем ключи
KEYS=$(sing-box generate reality-keypair)
PRIVATE_KEY=$(echo "$KEYS" | grep "PrivateKey" | awk '{print $2}')
PUBLIC_KEY=$(echo "$KEYS" | grep "PublicKey" | awk '{print $2}')

SHORT_ID=$(openssl -hex 8)
UUID=$(uuidgen)

echo "Выделен внутренний порт для Sing-box: $INTERNAL_PORT"

# Генерация конфига Sing-box
cat <<EOF > "$CONFIG_PATH"
{
  {
  "log": {
    "level": "info",
    "timestamp": true
  },
  "inbounds": [
    {
      "type": "trojan",
      "tag": "trojan-sys-in",
      "listen": "::",
      "listen_port": ;$INTERNAL_PORT,
      "users": [
        {
          "name": "ru-entry-node",
          "uuid": "$UUID",
          "flow": "xtls-rprx-vision"
        }
      ],
      "tls": {
        "enabled": true,
        "server_name": "www.apple.com",
        "reality": {
          "enabled": true,
          "handshake": {
            "server_options": {
              "server_name": "www.apple.com"
            }
          },
          "private_key": "$PRIVATE_KEY",
          "short_id": [
            "$SHORT_ID"
          ]
        }
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
Description=Sing-box Trojan Reality TCP EXIT Node Node (TMP_ID: ${TMP_ID})
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
              "sub_link_fp": "chrome",
              "node_public_key": "'"$PUBLIC_KEY"'"
           }
         }'

echo "=================================================="
echo "Sing-box VLESS REALITY TCP в качестве EXIT ноды развернута!"
echo "Порт:  $INTERNAL_PORT"
echo "Exit нода $TMP_ID установлена. Данные для подключения Entry Ноды"
echo "- UUID: $UUID"
echo "- PKEY: $PUBLIC_KEY"
echo "- SID: $SHORT_ID"
echo "=================================================="

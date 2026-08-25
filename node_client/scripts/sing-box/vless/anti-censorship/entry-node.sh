TMP_ID=$1

EXIT_HOST=$2
EXIT_PORT=$3
EXIT_PKEY=$4
EXIT_SID=$5
EXIT_UUID=$6

if [ -z "$TMP_ID" ] || [ -z "$EXIT_PORT" ] || [ -z "$EXIT_HOST" ] || [ -z "$EXIT_SID" ] || [ -z "$EXIT_PKEY" ] || [ -z "$EXIT_UUID" ]; then
    echo "Ошибка: Необходимы параметры для входной ноды: TMP_ID, IPV_ADDR, IP_VERSION!"
    echo "Ошибка: Необходимы параметры для оутбаунда выходной ноды: EXIT_HOST, EXIT_PORT, EXIT_SID, EXIT_PKEY, EXIT_UUID!"
    echo "Использование: bash sing-box-awg-install.sh <tmp_id> <ip_addr> <ip_version>"
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


# Извлекаем ключи
KEYS=$(sing-box generate reality-keypair)
PRIVATE_KEY=$(echo "$KEYS" | grep "PrivateKey" | awk '{print $2}')
PUBLIC_KEY=$(echo "$KEYS" | grep "PublicKey" | awk '{print $2}')

SHORT_ID=$(openssl -hex 8)


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
          "vless-in"
        ],
        "users": []
      }
    }
  },
  "inbounds": [
    {
      "type": "vless",
      "tag": "vless-in",
      "listen": "::",
      "listen_port": $INTERNAL_PORT,
      "users": [],
      "tls": {
        "enabled": true,
        "server_name": "$SNI",
        "reality": {
          "enabled": true,
          "handshake": {
            "server_options": {
              "server_name": "$SNI"
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
      "type": "vless",
      "tag": "proxy-exit",
      "server": "$EXIT_HOST",
      "server_port": $EXIT_PORT,
      "uuid": "$EXIT_UUID",
      "flow": "xtls-rprx-vision",
      "tls": {
        "enabled": true,
        "server_name": "www.apple.com",
        "utls": {
          "enabled": true,
          "fingerprint": "chrome"
        },
        "reality": {
          "enabled": true,
          "public_key": "$EXIT_PKEY",
          "short_id": "$EXIT_SID"
        }
      }
    },
    {
      "type": "direct",
      "tag": "direct"
    },
    {
      "type": "block",
      "tag": "block"
    }
  ],
  "route": {
      "rules": [
        {
          "protocol": [
            "bittorrent"
          ],
          "outbound": "block"
        },
        {
          "rule_set": [
            "geosite-ads",
            "geosite-malware"
          ],
          "outbound": "block"
        },
        {
          "domain_suffix": [
            ".ru",
            ".рф",
            ".su"
          ],
          "outbound": "direct"
        },
        {
          "rule_set": [
            "geosite-ru",
            "geoip-ru"
          ],
          "outbound": "direct"
        }
      ],
      "rule_set": [
        {
          "tag": "geosite-ru",
          "type": "remote",
          "format": "binary",
          "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-ru.srs",
          "download_detour": "direct"
        },
        {
          "tag": "geoip-ru",
          "type": "remote",
          "format": "binary",
          "url": "https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/geoip-ru.srs",
          "download_detour": "direct"
        },
        {
          "tag": "geosite-ads",
          "type": "remote",
          "format": "binary",
          "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-category-ads-all.srs",
          "download_detour": "direct"
        },
        {
          "tag": "geosite-malware",
          "type": "remote",
          "format": "binary",
          "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-malware.srs",
          "download_detour": "direct"
        }
      ],
      "final": "proxy-exit",
      "auto_detect_interface": true
   }
}
EOF

# Создание systemd сервиса
SERVICE_PATH="/etc/systemd/system/sing-box-${TMP_ID}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Sing-box VLESS Reality TCP Node (TMP_ID: ${TMP_ID})
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
echo "Sing-box VLESS REALITY TCP развернута."
echo "Внутренний порт:  $INTERNAL_PORT"
echo "=================================================="
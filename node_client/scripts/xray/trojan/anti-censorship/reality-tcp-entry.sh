#!/bin/bash
# Использование: bash vless-reality-tcp.sh <tmp_id>

TMP_ID=$1
EXIT_HOST=$2
EXIT_PORT=$3
EXIT_PUBKEY=$4
EXIT_SHORTID=$5
EXIT_PASSWORD=$6
EXIT_REALITY_SNI=$7

if [ -z "$TMP_ID" ] || [ -z "$EXIT_HOST" ] || [ -z "$EXIT_PASSWORD" ]; then
    echo "Ошибка: Недостаточно параметров!"
    echo "Использование: bash entry-node.sh <tmp_id> <exit_host> <exit_port> <exit_pubkey> <exit_shortid> <exit_password> <exit_reality_sni>"
    exit 1
fi

XRAY_BIN="/usr/local/bin/xray"
CONFIG_DIR="/opt/reinar_panel/configs"
CONFIG_PATH="$CONFIG_DIR/trojan-reality-tcp_${TMP_ID}.json"
PANEL_CALLBACK_URL="http://10.0.0.1/api/v1/nodes/protocols/callback" # Замени на IP твоей панели в сети Wireguard

mkdir -p "$CONFIG_DIR"

# 1. Функция поиска свободного порта
find_free_port() {
    local port=$1
    while ss -lnt | awk '{print $4}' | grep -q ":$port$"; do
        port=$((port + 1))
    done
    echo $port
}

# Ищем порты
API_PORT=$(find_free_port 10085)
INBOUND_PORT=$(find_free_port 443)

# 2. Генерация ключей для Reality
KEYS=$($XRAY_BIN x25519)
PRIVATE_KEY=$(echo "$KEYS" | grep "Private key:" | awk '{print $3}')
PUBLIC_KEY=$(echo "$KEYS" | grep "Public key:" | awk '{print $3}')
SHORT_ID=$(openssl rand -hex 8)

# 3. Формирование JSON конфига
# Важно: массив clients пуст, юзеров панель добавит позже через gRPC API
cat <<EOF > "$CONFIG_PATH"
{
  "log": {
    "loglevel": "warning"
  },
  "api": {
    "services": [
      "HandlerService",
      "LoggerService",
      "StatsService"
    ],
    "tag": "api"
  },
  "stats": {},
  "policy": {
    "levels": {
      "0": {
        "statsUserUplink": true,
        "statsUserDownlink": true
      }
    },
    "system": {
      "statsInboundUplink": true,
      "statsInboundDownlink": true,
      "statsOutboundUplink": true,
      "statsOutboundDownlink": true
    }
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
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "vk.com:443",
          "xver": 0,
          "serverNames": [
            "vk.com",
            "www.vk.com"
          ],
          "privateKey": "$PRIVATE_KEY",
          "shortIds": [
            "$SHORT_ID"
          ]
        }
      },
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls", "quic"]
      },
      "tag": "trojan-inbound"
    },
    {
      "listen": "127.0.0.1",
      "port": $API_PORT,
      "protocol": "dokodemo-door",
      "settings": {
        "address": "127.0.0.1"
      },
      "tag": "api"
    }
  ],
  "outbounds": [
    {
      "tag": "freedom_node",
      "protocol": "trojan",
      "settings": {
        "vnext": [
          {
            "address": "$EXIT_HOST",
            "port": $EXIT_PORT,
            "users": [
              {
                "password": "$EXIT_PASWORD"
              }
            ]
          }
        ]
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "serverName": "$EXIT_REALITY_SNI",
          "publicKey": "$EXIT_PUBKEY",
          "shortId": "$EXIT_SHORTID",
          "fingerprint": "chrome"
        }
      }
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

# 4. Создание Systemd юнита
SERVICE_PATH="/etc/systemd/system/xray-${TMP_ID}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Xray Custom Instance (TMP_ID: ${TMP_ID})
Documentation=https://xtls.github.io
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

# 5. Callback на панель (сообщаем, что всё готово)
# Передаем публичный ключ и short_id в кастомных полях, чтобы панель могла сразу собрать ссылки
curl -s -X POST "$PANEL_CALLBACK_URL" \
     -H "Content-Type: application/json" \
     -d '{
           "tmp_id": "'"$TMP_ID"'",
           "config_path": "'"$CONFIG_PATH"'",
           "metrics_port": '$INBOUND_PORT',
           "status": "installed",
           "spec_params": {
               "public_key": "'"$PUBLIC_KEY"'",
               "short_id": "'"$SHORT_ID"'"
           }
         }'

echo "Нода $TMP_ID успешно инициализирована. API Порт: $API_PORT, Inbound Порт: $INBOUND_PORT."
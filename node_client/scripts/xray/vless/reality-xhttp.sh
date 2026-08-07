#!/bin/bash
# Использование: bash vless-reality-tcp.sh <tmp_id>

TMP_ID=$1
if [ -z "$TMP_ID" ]; then
    echo "Ошибка: не передан tmp_id"
    exit 1
fi

XRAY_BIN="/usr/local/bin/xray"
CONFIG_DIR="/opt/reinar_panel/configs"
CONFIG_PATH="$CONFIG_DIR/vless-reality-tcp_${TMP_ID}.json"
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
XHTTP_PATH=$(openssl rand -hex 4)

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
      "listen": "127.0.0.1",
      "port": $API_PORT,
      "protocol": "dokodemo-door",
      "settings": {
        "address": "127.0.0.1"
      },
      "tag": "api"
    },
    {
      "listen": "0.0.0.0",
      "port": $INBOUND_PORT,
      "protocol": "vless",
      "settings": {
        "clients": [],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "xhttp",
        "xhttpSettings": {
          "mode": "auto",
          "host": "microsoft.com",
          "path": "xhttp-$XHTTP_PATH-vless-reality"
        }
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "microsoft.com:443",
          "xver": 0,
          "serverNames": [
            "microsoft.com",
            "www.microsoft.com"
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
      "tag": "vless-inbound"
    }
  ],
  "outbounds": [
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
    "rules": [
      {
        "inboundTag": ["api"],
        "outboundTag": "api_out",
        "type": "field"
      },
      {
        "ip": ["geoip:private"],
        "outboundTag": "block",
        "type": "field"
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
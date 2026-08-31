#!/bin/bash
# Использование: bash vless-tls-ws.sh <tmp_id> <domain>

TMP_ID=$1
CERT_PATH=$2
KEY_PATH=$3
DOMAIN=$4

if [ -z "$TMP_ID" ] || [ -z "$DOMAIN" ]; then
    echo "Ошибка: требуется tmp_id и domain"
    echo "Пример: bash vless-tls-ws.sh 1 mydomain.com"
    exit 1
fi

XRAY_BIN="/usr/local/bin/xray"
CONFIG_DIR="/etc/xray/configs"
CERT_DIR="/etc/xray/certs/$DOMAIN"
CONFIG_PATH="$CONFIG_DIR/${TMP_ID}.json"
PANEL_CALLBACK_URL="http://10.0.0.1/api/node/callback"

mkdir -p "$CONFIG_DIR" "$CERT_DIR"

# 1. Поиск свободных портов
find_free_port() {
    local port=$1
    while ss -lnt | awk '{print $4}' | grep -q ":$port$"; do
        port=$((port + 1))
    done
    echo $port
}

API_PORT=$(find_free_port 10085)
INBOUND_PORT=$(find_free_port 443)


# 3. Генерация пути для WebSocket
WS_PATH="/ws-$(openssl rand -hex 4)"

# 4. Формирование JSON конфига
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
      "protocol": "vless",
      "settings": {
        "clients": [],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "ws",
        "security": "tls",
        "tlsSettings": {
          "serverName": "$DOMAIN",
          "certificates": [
            {
              "certificateFile": "$CERT_PATH",
              "keyFile": "$KEY_PATH"
            }
          ]
        },
        "wsSettings": {
          "path": "$WS_PATH",
          "headers": {
            "Host": "$DOMAIN"
          }
        }
      },
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls", "quic"]
      },
      "tag": "inbound"
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
      "protocol": "freedom",
      "tag": "direct"
    },
    {
      "protocol": "blackhole",
      "tag": "block"
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

# 5. Systemd юнит
SERVICE_PATH="/etc/systemd/system/xray-${TMP_ID}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Xray Custom Instance VLESS-WS-TLS (TMP_ID: ${TMP_ID})
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

# 6. Callback в панель
curl -s -X POST "$PANEL_CALLBACK_URL" \
     -H "Content-Type: application/json" \
     -d '{
           "tmp_id": "'"$TMP_ID"'",
           "config_path": "'"$CONFIG_PATH"'",
           "api_port": '$API_PORT',
           "inbound_port": '$INBOUND_PORT',
           "status": "installed",
           "custom_fields": {
               "domain": "'"$DOMAIN"'",
               "path": "'"$WS_PATH"'"
           }
         }'

echo "Нода $TMP_ID (VLESS-WS-TLS) готова. Domain: $DOMAIN, Path: $WS_PATH"
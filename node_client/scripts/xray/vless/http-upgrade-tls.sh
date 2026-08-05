#!/bin/bash
# Использование: bash http-upgrade-tls.sh <tmp_id> <domain>

TMP_ID=$1
DOMAIN=$2

if [ -z "$TMP_ID" ] || [ -z "$DOMAIN" ]; then
    echo "Ошибка: требуется tmp_id и domain"
    echo "Пример: bash xray/vless/http-upgrade-tls.sh 1 mydomain.com"
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

# 2. Выпуск SSL сертификата через acme.sh (если еще не выпущен)
CERT_FILE="$CERT_DIR/fullchain.crt"
KEY_FILE="$CERT_DIR/privkey.key"

if [ ! -f "$CERT_FILE" ]; then
    echo "Выпускаем SSL сертификат для $DOMAIN..."
    curl https://get.acme.sh | sh -s email=admin@$DOMAIN
    ~/.acme.sh/acme.sh --set-default-ca --server letsencrypt
    ~/.acme.sh/acme.sh --issue -d "$DOMAIN" --standalone --httpport 80
    ~/.acme.sh/acme.sh --install-cert -d "$DOMAIN" \
        --key-file "$KEY_FILE" \
        --fullchain-file "$CERT_FILE"
fi

# 3. Генерация endpoint пути
HTTPUPGRADE_PATH="/http-$(openssl rand -hex 4)"

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
        "network": "httpupgrade",
        "security": "tls",
        "tlsSettings": {
          "serverName": "$DOMAIN",
          "certificates": [
            {
              "certificateFile": "$CERT_FILE",
              "keyFile": "$KEY_FILE"
            }
          ]
        },
        "httpupgradeSettings": {
          "path": "$HTTPUPGRADE_PATH",
          "host": "$DOMAIN"
        }
      }
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls", "quic"]
      },
      "tag": "inbound"
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
               "path": "'"$HTTPUPGRADE_PATH"'"
           }
         }'

echo "Нода $TMP_ID (VLESS-HTTPUPGRADE-TLS) готова. Domain: $DOMAIN, Path: $HTTPUPGRADE_PATH"
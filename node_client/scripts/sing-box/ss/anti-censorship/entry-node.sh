#!/bin/bash

METHOD_CHOICE=${1}
CERT_PATH=$2
KEY_PATH=$3
DOMAIN=$4

log() { echo -e "$1" >&2; }
log "Переменные окружения для этой вариации"

#EXIT_HOST=$5
#EXIT_PORT=$6
#EXIT_USER_PSK=$7
#EXIT_DOMAIN=$8
#EXIT_METHOD_CHOICE=${9}

if [ -z "$NODE_ID" ] || [ -z "$PROTO_ID" ] || [ -z "$EXIT_PORT" ] || [ -z "$EXIT_HOST" ] || [ -z "$EXIT_METHOD_CHOICE" ] || [ -z "$EXIT_USER_PSK" ] || [ -z "$EXIT_DOMAIN" ]; then
    log "Необходимо указать переменные окружения NODE_ID, PROTO_ID, EXIT_HOST, EXIT_PORT, EXIT_DOMAIN, EXIT_METHOD_CHOICE, EXIT_USER_PSK !"
    exit 1
fi

if [ -z "$CERT_PATH" ] || [ -z "$KEY_PATH" ] || [ -z "$DOMAIN" ]; then
    log "Ошибка: Не указан TMP_ID!"
    log "Использование: bash ss-ws-install.sh <METHOD_CHOICE> cert_path> <key_path> <domain>"
    exit 1
fi


if [ -z "$METHOD_CHOICE" ]; then
    echo "Выберите метод шифрования для ENTRY Node Shadowsocks-2022:"
    echo "1 - 2022-blake3-aes-128-gcm (быстрый, легкий)"
    echo "2 - 2022-blake3-aes-256-gcm (максимальная защита)"
    echo "3 - 2022-blake3-chacha20-poly1305 (лучше для мобильных без AES-инструкций)"
    read -p "Введите цифру (1-3) [по умолчанию 1]: " METHOD_CHOICE
fi

if [ -z "$EXIT_METHOD_CHOICE" ]; then
    echo "Укажите метод шифрования EXIT Node Shadowsocks-2022:"
    echo "1 - 2022-blake3-aes-128-gcm (быстрый, легкий)"
    echo "2 - 2022-blake3-aes-256-gcm (максимальная защита)"
    echo "3 - 2022-blake3-chacha20-poly1305 (лучше для мобильных без AES-инструкций)"
    read -p "Введите цифру (1-3) [по умолчанию 1]: " EXIT_METHOD_CHOICE
fi

if [ -z "$TITLE" ]; then
    log "Название для виртуальной ноды не указано. Будет использовано составное"
    TITLE="Vnode_PrId-'$PROTO_ID'_NId-'$NODE_ID'"
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
# Маппинг цифры в параметры
case "$EXIT_METHOD_CHOICE" in
    2)
        EXIT_SS_METHOD="2022-blake3-aes-256-gcm"
        ;;
    3)
        EXIT_SS_METHOD="2022-blake3-chacha20-poly1305"
        ;;
    *)
        # Дефолтный fallback на 128-gcm
        EXIT_SS_METHOD="2022-blake3-aes-128-gcm"
        ;;
esac

SINGBOX_BIN="/usr/local/bin/sing-box"
CONFIG_DIR="/etc/reinar/configs/sing-box/wh_list"
PANEL_CALLBACK_URL="http://10.0.0.1:$ADMIN_PANEL_PORT/api/v1/server/nodes/protocols/register"
PANEL_CONFIRM_URL="http://10.0.0.1:$ADMIN_PANEL_PORT/api/v1/server/nodes/protocols/confirm"

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

log "Выделен внутренний порт для Sing-box: $INTERNAL_PORT"

log "1. Регистрация ноды в панели и получение node_proto_id..."

REG_RESPONSE=$(mktemp)
HTTP_CODE=$(curl -s -w "%{http_code}" -o "$REG_RESPONSE" -X POST "$PANEL_CALLBACK_URL" \
     -H "Content-Type: application/json" \
     -d '{
           "proto_id": '"$PROTO_ID"',
           "node_id": '"$NODE_ID"',
           "proto_port": '"$INTERNAL_PORT"',
           "metrics_port": '"$METRICS_PORT"',
           "title": "'"$TITLE"'",
           "constant_node_data_obj": {
              "node_method": "'$SS_METHOD'"
           }
         }')

if [ "$HTTP_CODE" -ne 200 ]; then
    log "\033[31mОшибка регистрации (HTTP $HTTP_CODE): $(cat "$REG_RESPONSE")\033[0m"
    rm -f "$REG_RESPONSE"
    exit 1
fi

NODE_PROTO_ID=$(jq -r '.node_proto_id' "$REG_RESPONSE")
TITLE=$(jq -r '.title' "$REG_RESPONSE")
rm -f "$REG_RESPONSE"

log "Назначен NODE_PROTO_ID: $NODE_PROTO_ID"

CONFIG_PATH="$CONFIG_DIR/ss-tls-tcp-entry-${NODE_PROTO_ID}.json"
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
      "type": "shadowsocks",
      "tag": "proxy-exit",
      "server": "$EXIT_HOST",
      "server_port": $EXIT_PORT,
      "method": "$EXIT_SS_METHOD",
      "password": "$EXIT_USER_PSK",
      "tls": {
        "enabled": true,
        "server_name": "$EXIT_DOMAIN",
        "utls": {
          "enabled": true,
          "fingerprint": "chrome"
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
SERVICE_NAME="reinar-ss-${NODE_PROTO_ID}"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Sing-box Shadowsocks TLS TCP Entry Node (TMP_ID: ${TMP_ID})
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

log "2. Запуск юнита $SERVICE_NAME..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >&2
systemctl restart "$SERVICE_NAME" >&2

sleep 1

if ! systemctl is-active --quiet "$SERVICE_NAME"; then
    log "\033[31mСервис $SERVICE_NAME не смог запуститься! Откат...\033[0m"
    systemctl stop "$SERVICE_NAME" || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$CONFIG_PATH" "$SERVICE_PATH"
    systemctl daemon-reload

    # Оповещаем панель о фейле
    curl -s -X POST "$PANEL_CONFIRM_URL" -H "Content-Type: application/json" \
         -d '{"node_proto_id": '"$NODE_PROTO_ID"', "status": 3}' >/dev/null || true
    exit 1
fi

# 6. Финализация статуса в панели
curl -s -X POST "$PANEL_CONFIRM_URL" -H "Content-Type: application/json" \
     -d '{
        "node_proto_id": '"$NODE_PROTO_ID"',
        "status": 2,
        "reload_core_command": "systemctl restart '"$SERVICE_NAME"'",
        "config_path": "'"$CONFIG_PATH"'",
     }' >/dev/null


log "=================================================="
log "✓ Виртуальная нода успешно создана!"
log "Node Proto ID: $NODE_PROTO_ID"
log "Config Path: $CONFIG_PATH"
log "Title: $TITLE"
log "Основной Порт: $INTERNAL_PORT"
log "=================================================="

# 7. Возврат результата в stdout (JSON) для вызывающего скрипта
jq -n \
  --arg node_proto_id "$NODE_PROTO_ID" \
  --arg service_name "$SERVICE_NAME" \
  '{node_proto_id: $node_proto_id, service_name: $service_name}'

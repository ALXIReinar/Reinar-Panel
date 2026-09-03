#!/bin/bash

# Адреса самого сервера внутри туннеля (с маской). Передаются из панели.
# Пример: 10.1.0.1/16
IP_ADDR=$1
# Пример: fd00:1::1/64
IP_VERSION=$2

log() { echo -e "$1" >&2; }
log "Зависимости-переменные окружения для оутбаунда"
#EXIT_HOST=$4
#EXIT_PORT=$5
#EXIT_PKEY=$6
#EXIT_SID=$7
#EXIT_UUID=$8

if [ -z "$NODE_ID" ] || [ -z "$PROTO_ID" ] ||  [ -z "$EXIT_PORT" ] || [ -z "$EXIT_HOST" ] || [ -z "$EXIT_SID" ] || [ -z "$EXIT_PKEY" ] || [ -z "$EXIT_UUID" ]; then
    log "Ошибка: Необходимы параметры для входной ноды: TMP_ID, IPV_ADDR, IP_VERSION!"
    log "Ошибка: Необходимы параметры для оутбаунда выходной ноды: EXIT_HOST, EXIT_PORT, EXIT_SID, EXIT_PKEY, EXIT_UUID!"
    exit 1
fi

if [ -z "$IP_ADDR" ] || [ -z "$IP_VERSION" ]; then
    log "Ошибка: Необходимы параметры IP_ADDR, IP_VERSION !"
    log "Использование: bash node_client/scripts/sing-box/wg/anti-censorship/awg/entry-node.sh <ip_addr> <ip_version>"
    exit 1
fi

if [[ "$IP_VERSION" != "4" && "$IP_VERSION" != "6" ]]; then
    log "IP_VERSION must be 4 or 6"
    exit 1
fi
if [ -z "$TITLE" ]; then
    log "Название для виртуальной ноды не указано. Будет использовано составное"
    TITLE="Vnode_PrId-'$PROTO_ID'_NId-'$NODE_ID'"
fi
# Используем кастомный бинарник!
SINGBOX_BIN="/usr/local/bin/sing-box-awg"
CONFIG_DIR="/etc/reinar/configs/sing-box-awg/wh_list"
PANEL_CALLBACK_URL="http://10.0.0.1:$ADMIN_PANEL_PORT/api/v1/server/nodes/protocols/register"
PANEL_CONFIRM_URL="http://10.0.0.1:$ADMIN_PANEL_PORT/api/v1/server/nodes/protocols/confirm"

mkdir -p "$CONFIG_DIR"

# Функция поиска свободного порта
find_free_port() {
    local port=$1
    while ss -lntu | awk '{print $4}' | grep -q ":$port$"; do
        port=$((port + 1))
    done
    echo $port
}

INTERNAL_PORT=$(find_free_port 51820)
METRICS_PORT=$(find_free_port 10085)

# --- 1. ГЕНЕРАЦИЯ КЛЮЧЕЙ СЕРВЕРА ---
WG_KEYS=$($SINGBOX_BIN generate wg-keypair)
WG_PRIVATE_KEY=$(echo "$WG_KEYS" | grep PrivateKey | awk '{print $2}')
WG_PUBLIC_KEY=$(echo "$WG_KEYS" | grep PublicKey | awk '{print $2}')
NODE_HASH_SALT=$(openssl rand -base64 12)

log "Выделен порт для AmneziaWG: $INTERNAL_PORT"

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
               "node_public_key": "'"$WG_PUBLIC_KEY"'",
               "node_ipv'"$IP_VERSION"'_subnet": "'"$IP_ADDR"'",
               "node_hash_salt": '"$NODE_HASH_SALT"'
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
# --- 2. ГЕНЕРАЦИЯ ПАРАМЕТРОВ ОБФУСКАЦИИ (AWG) ---
# Генерируем уникальный профиль маскировки для каждой ноды
JC=$(( RANDOM % 10 + 3 ))           # от 3 до 12
JMIN=$(( RANDOM % 20 + 40 ))        # от 40 до 59
JMAX=$(( RANDOM % 300 + 700 ))      # от 700 до 999
S1=$(( RANDOM % 100 + 15 ))         # от 15 до 114
S2=$(( RANDOM % 100 + 15 ))         # от 15 до 114

# H1-H4 - большие случайные числа (магические заголовки)
# Bash RANDOM генерирует от 0 до 32767, комбинируем для получения больших int
generate_magic() { echo $(( (RANDOM << 15) | RANDOM )); }
H1=$(generate_magic)
H2=$(generate_magic)
H3=$(generate_magic)
H4=$(generate_magic)

# Генерация конфига Sing-box
CONFIG_PATH="$CONFIG_DIR/awg-${NODE_PROTO_ID}.json"
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
          "awg-in"
        ],
        "users": []
      }
    }
  },
  "inbounds": [
    {
      "type": "wireguard",
      "tag": "awg-in",
      "listen": "::",
      "listen_port": $INTERNAL_PORT,
      "system": false,
      "local_address": [
        "$IP_ADDR"
      ],
      "private_key": "$WG_PRIVATE_KEY",
      "peers": [],
      "jc": $JC,
      "jmin": $JMIN,
      "jmax": $JMAX,
      "s1": $S1,
      "s2": $S2,
      "h1": $H1,
      "h2": $H2,
      "h3": $H3,
      "h4": $H4
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
        "server_name": "www.microsoft.com",
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
SERVICE_NAME="reinar-awg-${NODE_PROTO_ID}"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
cat <<EOF > "$SERVICE_PATH"
[Unit]
Description=Fork Sing-box AmneziaWG Entry Node (NODE_PROTO_ID: ${NODE_PROTO_ID})
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
log "AmneziaWG развернут (кастомное Sing-Box ядро)."
log "Node Proto ID: $NODE_PROTO_ID"
log "Config Path: $CONFIG_PATH"
log "Title: $TITLE"
log "Основной Порт: $INTERNAL_PORT"
log "Public Key: $WG_PUBLIC_KEY"
log "Обфускация: JC=$JC, JMIN=$JMIN, JMAX=$JMAX"
log "=================================================="


# 7. Возврат результата в stdout (JSON) для вызывающего скрипта
jq -n \
  --arg node_proto_id "$NODE_PROTO_ID" \
  --arg service_name "$SERVICE_NAME" \
  '{node_proto_id: $node_proto_id, service_name: $service_name}'

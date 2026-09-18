#!/bin/bash
set -e

DOMAIN=$1
EMAIL=$2
CERT_DIR=${3:-"/etc/reinar/certs/$DOMAIN"}
SERVICES_LIST="$CERT_DIR/services.list"

log() { echo -e "$1" >&2; }

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    log "\033[31mОшибка: Не указаны параметры! bash prepare-cert.sh <domain> <email>\033[0m"
    exit 1
fi

log "1. Подготовка сертификата для $DOMAIN..."
mkdir -p "$CERT_DIR"
touch "$SERVICES_LIST" # Создаем пустой файл, если его нет

apt-get update -y > /dev/null 2>&1
apt-get install -y curl socat cron jq > /dev/null 2>&1

if [ ! -f "$HOME/.acme.sh/acme.sh" ]; then
    log "Установка acme.sh..."
    curl -s https://get.acme.sh | sh -s email="$EMAIL" > /dev/null 2>&1
fi
source "$HOME/.acme.sh/acme.sh.env"

# Если сертификата еще нет - выпускаем
if [ ! -f "$CERT_DIR/fullchain.cer" ]; then
    log "Запрашиваем новый сертификат (Let's Encrypt / ZeroSSL)..."
    if ! "$HOME/.acme.sh/acme.sh" --issue -d "$DOMAIN" --standalone --keylength ec-256 --server letsencrypt >&2; then
        if ! "$HOME/.acme.sh/acme.sh" --issue -d "$DOMAIN" --standalone --keylength ec-256 --server zerossl >&2; then
            log "\033[31mОшибка выпуска сертификата.\033[0m"
            exit 1
        fi
    fi

    # Устанавливаем сертификат и вешаем хук
    # Флаг -r у xargs важен: если список пуст, команда не упадет с ошибкой
    RELOAD_CMD="xargs -r -a $SERVICES_LIST -I {} systemctl try-restart {}"

    "$HOME/.acme.sh/acme.sh" --install-cert -d "$DOMAIN" --ecc \
        --fullchain-file "$CERT_DIR/fullchain.cer" \
        --key-file "$CERT_DIR/private.key" \
        --reloadcmd "$RELOAD_CMD" >&2
else
    log "Сертификат уже существует. Пропускаем выпуск."
fi

log "=================================================="
log "✓ УСПЕХ! Сертификат готов к использованию."
log "Домен: $DOMAIN"
log "Хук перезапуска охватывает: $(cat $SERVICES_LIST | tr '\n' ' ')"
log "=================================================="

export DOMAIN=$DOMAIN
export CERT_PATH="$CERT_PATH/fullchain.cer"
export KEY_PATH="$CERT_PATH/private.key"
export SERVICES_LIST=$SERVICES_LIST
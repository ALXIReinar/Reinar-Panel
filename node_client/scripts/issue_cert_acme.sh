#!/bin/bash

DOMAIN=$1
EMAIL=$2
CERT_DIR=${3:-"/etc/xray/certs/$1"}

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    echo "Ошибка: Не указан домен или email!"
    echo "Использование: bash issue-cert.sh <domain> <email>"
    exit 1
fi

echo "Начинаем процесс получения сертификата для $DOMAIN ($EMAIL)..."

# 1. Установка необходимых зависимостей (socat нужен для acme.sh standalone)
apt-get update -y
apt-get install -y curl socat cron

# 2. Установка acme.sh (если еще не установлен)
if [ ! -f "$HOME/.acme.sh/acme.sh" ]; then
    echo "Установка acme.sh..."
    curl https://get.acme.sh | sh -s email="$EMAIL"
fi

# Делаем алиас доступным в текущем скрипте
source "$HOME/.acme.sh/acme.sh.env"

# 3. Выпуск сертификата (ECC/ec-256 работает быстрее и безопаснее)
echo "Попытка выпуска через Let's Encrypt..."
"$HOME/.acme.sh/acme.sh" --set-default-ca --server letsencrypt
"$HOME/.acme.sh/acme.sh" --issue -d "$DOMAIN" --standalone --keylength ec-256

# Проверка на ошибку Let's Encrypt (код возврата не равен 0)
if [ $? -ne 0 ]; then
    echo "Let's Encrypt вернул ошибку. Пробуем fallback на ZeroSSL..."
    "$HOME/.acme.sh/acme.sh" --set-default-ca --server zerossl
    "$HOME/.acme.sh/acme.sh" --issue -d "$DOMAIN" --standalone --keylength ec-256

    if [ $? -ne 0 ]; then
        echo "Ошибка: Не удалось получить сертификат ни через Let's Encrypt, ни через ZeroSSL."
        echo "Убедитесь, что A-запись домена $DOMAIN указывает на этот IP и порт 80 открыт."
        exit 1
    fi
fi

# 4. Установка сертификата в рабочую директорию Xray
# Мы используем --install-cert, чтобы acme.sh запомнил эти пути для автообновления
mkdir -p "$CERT_DIR"

# Команда reloadcmd будет выполняться cron'ом каждые 60 дней после обновления сертификата.
# Так как наши systemd-сервисы называются xray-<tmp_id>.service, мы перезапускаем их по маске.
RELOAD_CMD="systemctl daemon-reload && systemctl try-restart 'xray-*'"

echo "Установка сертификата и настройка cron-хуков..."
"$HOME/.acme.sh/acme.sh" --install-cert -d "$DOMAIN" --ecc \
    --fullchain-file "$CERT_DIR/fullchain.cer" \
    --key-file "$CERT_DIR/private.key" \
    --reloadcmd "$RELOAD_CMD"

if [ $? -eq 0 ]; then
    echo "=================================================="
    echo "УСПЕХ! Сертификат успешно выпущен и установлен."
    echo "Путь к сертификату: $CERT_DIR/fullchain.cer"
    echo "Путь к ключу:       $CERT_DIR/private.key"
    echo "Cron для автообновления настроен."
    echo "=================================================="
else
    echo "Произошла ошибка при копировании сертификатов."
    exit 1
fi
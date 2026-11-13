#!/bin/bash

echo "Начинаем установку ядра Sing-box..."

# 1. Определение архитектуры
ARCH=$(uname -m)
case "$ARCH" in
    x86_64) SB_ARCH="amd64" ;;
    aarch64) SB_ARCH="arm64" ;;
    *)
        echo "Ошибка: Архитектура $ARCH не поддерживается этим скриптом."
        exit 1
        ;;
esac

echo "Обнаружена архитектура: $SB_ARCH"

# 2. Получение ссылки на последний релиз через GitHub API
# Ищем архив вида linux-amd64.tar.gz (без CGO и прочих специфичных суффиксов)
LATEST_URL=$(curl -sL https://api.github.com/repos/SagerNet/sing-box/releases/latest \
    | grep "browser_download_url" \
    | grep "linux-${SB_ARCH}.tar.gz\"" \
    | head -n 1 \
    | cut -d '"' -f 4)

if [ -z "$LATEST_URL" ]; then
    echo "Ошибка: Не удалось найти ссылку на скачивание последней версии Sing-box."
    exit 1
fi

echo "Скачивание архива: $LATEST_URL"
wget -qO sing-box.tar.gz "$LATEST_URL"

# 3. Распаковка архива
echo "Распаковка..."
tar -xzf sing-box.tar.gz

# Определяем имя извлеченной папки (она содержит номер версии, например sing-box-1.8.1-linux-amd64)
DIR_NAME=$(tar -tf sing-box.tar.gz | head -1 | cut -f1 -d"/")

# 4. Установка бинарника
mv "$DIR_NAME/sing-box" /usr/local/bin/
chmod +x /usr/local/bin/sing-box

# 5. Очистка временных файлов
rm -rf sing-box.tar.gz "$DIR_NAME"

# 6. Создание директории для конфигураций нод
CONFIG_DIR="/etc/sing-box/configs"
mkdir -p "$CONFIG_DIR"

# 7. Ставим xray для метрик
echo "Ставим xray для сбора метрик"
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install


echo "=================================================="
echo "Ядро Sing-box успешно установлено!"
echo "Версия:"
sing-box version
echo "Директория конфигураций: $CONFIG_DIR"
echo "=================================================="
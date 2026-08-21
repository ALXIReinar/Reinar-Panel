#!/bin/bash
set -e

# Репозиторий форка
REPO="hoaxisr/amnezia-box"
# Новое имя бинарника, чтобы не конфликтовать с оригиналом
BIN_NAME="sing-box-awg"
INSTALL_DIR="/usr/local/bin"

echo "==> Установка форка sing-box (AmneziaWG) рядом с основным ядром..."

# 1. Определяем архитектуру
ARCH=$(uname -m)
case "$ARCH" in
    x86_64) ARCH="amd64" ;;
    aarch64) ARCH="arm64" ;;
    *) echo "❌ Архитектура $ARCH не поддерживается."; exit 1 ;;
esac
OS="linux"
echo "✅ Архитектура: $OS-$ARCH"

# 2. Получаем ссылку на последний релиз форка
echo "🔍 Поиск последнего релиза в $REPO..."
DOWNLOAD_URL=$(curl -s https://api.github.com/repos/$REPO/releases/latest | grep "browser_download_url.*$OS-$ARCH.*\.tar\.gz" | cut -d '"' -f 4)

if [ -z "$DOWNLOAD_URL" ]; then
    echo "❌ Ошибка: Не удалось найти .tar.gz архив для $OS-$ARCH в $REPO."
    exit 1
fi

# 3. Скачиваем и распаковываем во временную папку
echo "⬇️ Скачиваем архив: $DOWNLOAD_URL"
wget -q -O /tmp/sing-box-awg.tar.gz "$DOWNLOAD_URL"

echo "📦 Распаковываем..."
mkdir -p /tmp/sing-box-awg
tar -xzf /tmp/sing-box-awg.tar.gz -C /tmp/sing-box-awg

# 4. Ищем бинарник внутри распакованной папки
FIND_BIN=$(find /tmp/sing-box-awg -type f -name "sing-box")
if [ -z "$FIND_BIN" ]; then
    echo "❌ Ошибка: исполняемый файл не найден в архиве!"
    exit 1
fi

# 5. Копируем с новым именем sing-box-awg
echo "⚙️ Устанавливаем бинарный файл в $INSTALL_DIR/$BIN_NAME..."
mv "$FIND_BIN" "$INSTALL_DIR/$BIN_NAME"
chmod +x "$INSTALL_DIR/$BIN_NAME"

# 6. Уборка
rm -rf /tmp/sing-box-awg /tmp/sing-box-awg.tar.gz

echo "✅ Проверка версии кастомного ядра:"
"$INSTALL_DIR/$BIN_NAME" version

echo "=================================================="
echo "🎉 Форк успешно установлен в $INSTALL_DIR/$BIN_NAME."
echo "Оригинальный sing-box не затронут."
echo "=================================================="
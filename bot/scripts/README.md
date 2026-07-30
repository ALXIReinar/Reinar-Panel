# 🤖 Telegram Bot - Скрипты установки

Скрипты для автоматизированной установки и управления Telegram ботом.

## 📋 Список скриптов

### `install.sh` - Основной скрипт установки

Устанавливает Telegram бот в `/opt/vpn-panel/bot/` с полной конфигурацией.

**Требования:**
- Docker и Docker Compose
- Права root/sudo
- Linux (Ubuntu/Debian/CentOS)

**Интерактивная установка:**

```bash
sudo bash bot/scripts/install.sh
```

**CI/CD установка** (без интерактивного ввода):

```bash
# Экспортируем переменные окружения
export BOT_TOKEN="123456789:ABCDEF..."
export SUB_SERVICE_URL="http://127.0.0.1:8000"
export ADMIN_TG_ID="1252118203"
export REDIS_HOST="127.0.0.1"
export REDIS_PORT="6379"
export REDIS_PASSWORD="YourSecurePassword"

# Запускаем установку
sudo -E bash bot/scripts/install.sh
```

**Что запрашивается при интерактивной установке:**

| Переменная | Описание | Пример |
|------------|----------|--------|
| `BOT_TOKEN` | Токен бота от @BotFather | `123456789:ABCDEF...` |
| `SUB_SERVICE_URL` | URL Admin Panel API | `http://127.0.0.1:8000` |
| `ADMIN_TG_ID` | Telegram ID администратора | `1252118203` |
| `REDIS_HOST` | Хост Redis | `127.0.0.1` (по умолчанию) |
| `REDIS_PORT` | Порт Redis | `6379` (по умолчанию) |
| `REDIS_PASSWORD` | Пароль Redis | Генерируется автоматически |

**Что делает скрипт:**

1. ✅ Проверяет права root
2. ✅ Проверяет наличие Docker и Docker Compose
3. ✅ Создаёт `/opt/vpn-panel/bot/`
4. ✅ Копирует файлы проекта
5. ✅ Создаёт `.env` и `.env.bot.prod`
6. ✅ Собирает и запускает Docker контейнер
7. ✅ Настраивает права доступа
8. ✅ Проверяет статус контейнера

---

### `uninstall.sh` - Скрипт удаления

Полностью удаляет Telegram бот из системы.

**Интерактивное удаление:**

```bash
sudo bash bot/scripts/uninstall.sh
```

**CI/CD удаление** (без подтверждения):

```bash
export CONFIRM_UNINSTALL="yes"
sudo -E bash bot/scripts/uninstall.sh
```

**Что удаляется:**

- ❌ Контейнер Docker
- ❌ Все файлы в `/opt/vpn-panel/bot/`
- ❌ Конфигурационные файлы
- ❌ Логи бота

---

## 🚀 Быстрый старт

### 1. Установка бота

```bash
# Клонируйте репозиторий
cd /path/to/ReinarPanel

# Запустите установку
sudo bash bot/scripts/install.sh
```

### 2. Проверка статуса

```bash
cd /opt/vpn-panel/bot
docker compose ps
docker compose logs -f
```

### 3. Управление ботом

```bash
# Остановка
docker compose down

# Запуск
docker compose up -d

# Перезапуск
docker compose restart

# Просмотр логов
docker compose logs -f
```

---

## 🔧 Ручная настройка

Если нужно изменить конфигурацию после установки:

1. Отредактируйте `/opt/vpn-panel/bot/.env.bot.prod`
2. Перезапустите бот: `docker compose restart`

---

## 🐛 Troubleshooting

### Бот не отвечает

```bash
# Проверьте логи
docker compose logs -f

# Проверьте статус контейнера
docker compose ps
```

### Проблемы с правами

```bash
# Исправьте права
sudo chown -R 1000:1000 /opt/vpn-panel/bot/
sudo chmod -R 777 /opt/vpn-panel/bot/bot_logs
```

### Переустановка

```bash
# Удалите старую установку
sudo bash bot/scripts/uninstall.sh

# Установите заново
sudo bash bot/scripts/install.sh
```

---

## 📁 Структура после установки

```
/opt/vpn-panel/bot/
├── .env                    # Docker Compose конфигурация
├── .env.bot.prod          # Конфигурация бота
├── docker-compose.yml     # Docker Compose файл
├── Dockerfile             # Docker образ
├── requirements.txt       # Python зависимости
├── bot_logs/             # Логи бота
├── core/                 # Исходный код
├── config_dir/           # Конфигурация
└── tests/                # Тесты
```

---

## 🔐 Безопасность

- ⚠️ Не коммитьте `.env` файлы в Git
- ⚠️ Используйте сильные пароли для Redis
- ⚠️ Ограничьте доступ к `/opt/vpn-panel/bot/`
- ⚠️ Регулярно обновляйте Docker образы

---

## 📞 Поддержка

При возникновении проблем:

1. Проверьте логи: `docker compose logs -f`
2. Проверьте конфигурацию в `.env.bot.prod`
3. Убедитесь что Admin Panel API доступен по `SUB_SERVICE_URL`
4. Проверьте что `ADMIN_TG_ID` корректен


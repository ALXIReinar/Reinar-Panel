# Проверка шаблонов виртуальных нод

Запускайте команды от root на dev-стенде из каталога `vnode_checker/`.
Нужны Python 3.12, рабочие админка, саб-сервис, нод-клиент и PostgreSQL.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp checker.example.yaml checker.yaml
```

В `checker.yaml` укажите физическую ноду, тестовые подписку и план, адреса сервисов,
доступный с хоста адрес PostgreSQL и путь к файлу параметров БД. Соединение с БД работает в режиме
`READ ONLY`. Для OpenAPI и приватных маршрутов админки действует `allowed_ips` или JWT.
Если нужен JWT, передайте `VNODE_CHECKER_ACCESS_TOKEN` и при необходимости
`VNODE_CHECKER_REFRESH_TOKEN` через окружение процесса. Для TLS задайте `domain` и `email`.
Для S2 сверьте `collector_log_args` и интервал коллектора ARQ с настройками стенда.

```bash
.venv/bin/python -m vnode_checker manifest generate --no-prompt
.venv/bin/python -m vnode_checker manifest lint
.venv/bin/python -m vnode_checker manual print xray-vless-reality-xhttp
.venv/bin/python -m vnode_checker sweep --only xray-vless-reality-xhttp
.venv/bin/python -m vnode_checker verify --template xray-vless-reality-xhttp
.venv/bin/python -m vnode_checker report coverage
```

Записи `unresolved` в манифесте сохраняют пропуск до решения владельца. После выбора скрипта
укажите `install_script`, проверьте `tls` и `cdn`, затем очистите `skip` и повторите линт.
`sweep` выполняет S1 и S1.5. Флаг `--interactive` добавляет проверку с телефона.
`--from` начинает с указанного шаблона в порядке прогона, `--resume` продолжает по ID прогона,
`--continue-on-fail` позволяет перейти к следующему шаблону после сбоя с успешной отвязкой.

Для `verify` можно указать `--node-proto-id` вместо `--template`. Выбранная нода должна иметь
успешный результат S1 в журнале прогонов. Если тестовый план содержит другие локации или на
физической ноде работают другие VPN-unit, прогон останавливается на проверке изоляции.
Перед CDN-прогоном подтвердите готовность DNS и Cloudflare в интерактивном запросе или флагом
`--confirm-cdn-ready`. Для sing-box нужна проверенная сборка с `with_v2ray_api`.

Отчёт сохраняется в `runs/results.jsonl`. Логи и снимки в `runs/` могут содержать конфиги и ссылки
подключения. После прогона инструмент отвязывает и останавливает проверенную ноду. Для
`verify --keep-running` успешно проверенная нода остаётся запущенной до следующего прогона.
Файлы, unit, записи нод и сертификаты остаются для ручной очистки владельцем.

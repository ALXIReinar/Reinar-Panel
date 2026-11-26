#!/bin/bash
set -euo pipefail

SING_BOX_VERSION=1.14.4
SING_BOX_SHA256=0958ccd23b1ea9a141d715d15478b1e040fd04bcca19d8ff5529636b1b753e18
GO_VERSION=1.26.11

case "$(uname -m)" in
    x86_64)
        go_arch=amd64
        go_sha256=9849f4e04ee35303714e34fbc3ac8ab44ea3e448a95aa182f91e3b9b79c710ec
        ;;
    aarch64)
        go_arch=arm64
        go_sha256=6c2f29b458b5add0835f18b776f69c8881a6d88428f1484a6da55755e620757e
        ;;
    *)
        echo "Ошибка: поддерживаются архитектуры x86_64 и aarch64." >&2
        exit 1
        ;;
esac

bin_dir="${DESTDIR:-}/usr/local/bin"
config_dir="${DESTDIR:-}/etc/sing-box/configs"
if [[ -z "${DESTDIR:-}" && "$EUID" -ne 0 ]]; then
    echo "Для установки запустите скрипт с правами root." >&2
    exit 1
fi

work_dir=$(mktemp -d)
staged_binary=
cleanup() {
    if [[ -n "$staged_binary" ]]; then
        rm -f -- "$staged_binary"
    fi
    rm -rf -- "$work_dir"
}
trap cleanup EXIT

echo "Скачиваем исходники sing-box $SING_BOX_VERSION и Go $GO_VERSION ($go_arch)."
curl -fsSL --retry 3 "https://codeload.github.com/SagerNet/sing-box/tar.gz/refs/tags/v$SING_BOX_VERSION" \
    -o "$work_dir/sing-box.tar.gz"
curl -fsSL --retry 3 "https://go.dev/dl/go$GO_VERSION.linux-$go_arch.tar.gz" -o "$work_dir/go.tar.gz"
(
    cd "$work_dir"
    printf '%s  %s\n' "$SING_BOX_SHA256" sing-box.tar.gz "$go_sha256" go.tar.gz | sha256sum --check --status
)
tar -xzf "$work_dir/sing-box.tar.gz" -C "$work_dir"
tar -xzf "$work_dir/go.tar.gz" -C "$work_dir"

echo "Собираем sing-box с поддержкой V2Ray API."
(
    cd "$work_dir/sing-box-$SING_BOX_VERSION"
    tags=$(cat release/DEFAULT_BUILD_TAGS_OTHERS)
    ldflags=$(cat release/LDFLAGS)
    CGO_ENABLED=0 GOOS=linux GOARCH="$go_arch" GOTOOLCHAIN=local \
        "$work_dir/go/bin/go" build -mod=readonly -trimpath -buildvcs=false \
        -tags "$tags,with_v2ray_api" \
        -ldflags "$ldflags -X github.com/sagernet/sing-box/constant.Version=$SING_BOX_VERSION -s -w" \
        -o "$work_dir/sing-box" ./cmd/sing-box
)

echo 'Проверяем, что бинарник принимает конфигурацию V2Ray API.'
"$work_dir/sing-box" check -c /dev/stdin <<'EOF'
{"experimental":{"v2ray_api":{"listen":"127.0.0.1:10085","stats":{"enabled":true}}}}
EOF

# Заменяем рабочий бинарник только после успешной сборки и проверки.
mkdir -p -- "$bin_dir" "$config_dir"
staged_binary=$(mktemp "$bin_dir/.sing-box.XXXXXXXX")
install -m 0755 -- "$work_dir/sing-box" "$staged_binary"
mv -fT -- "$staged_binary" "$bin_dir/sing-box"
staged_binary=

"$bin_dir/sing-box" version
echo "Директория конфигураций: $config_dir"

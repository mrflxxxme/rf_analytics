#!/usr/bin/env bash
# Проверка внутреннего Caddyfile (T2.5, D27): страницы фактов индексируются только на своём домене,
# приложение, 404 и временный адрес *.sslip.io — noindex. Запуск из корня репозитория (CI: web.yml).
set -euo pipefail
img=caddy:2.8.4-alpine
cf="$PWD/deploy/Caddyfile"
docker run --rm -v "$cf:/etc/caddy/Caddyfile:ro" "$img" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

root=$(mktemp -d)
mkdir -p "$root/fakty/nisha/x" "$root/metodologiya" "$root/karta/assets"
for f in index.html fakty/nisha/x/index.html metodologiya/index.html karta/index.html sitemap.xml robots.txt \
         karta/assets/a.js; do
  echo ok > "$root/$f"
done
chmod -R a+rX "$root"
docker run -d --name caddy-check -p 127.0.0.1:18080:8080 -v "$cf:/etc/caddy/Caddyfile:ro" -v "$root:/srv/static:ro" \
  "$img" > /dev/null
trap 'docker rm -f caddy-check > /dev/null' EXIT
for _ in $(seq 30); do curl -fs -o /dev/null http://127.0.0.1:18080/ && break; sleep 1; done

fail=0
check() {  # host path ожидание(index|noindex) [код]
  local h
  h=$(curl -s -D - -o /dev/null -H "Host: $1" "http://127.0.0.1:18080$2")
  local code robots
  code=$(head -1 <<< "$h" | awk '{print $2}')
  robots=$(grep -i '^x-robots-tag:' <<< "$h" | tr -d '\r' || true)
  local got=index
  [[ -n "$robots" ]] && got=noindex
  if [[ "$got" == "$3" && "$code" == "${4:-200}" ]]; then
    echo "ok   $1$2 → $code $got"
  else
    echo "FAIL $1$2 → $code $got (ждали ${4:-200} $3)"; fail=1
  fi
}
check nishemer.ru / index
check nishemer.ru /fakty/nisha/x/ index
check nishemer.ru /metodologiya/ index
check nishemer.ru /sitemap.xml index
check nishemer.ru /robots.txt index
check nishemer.ru /karta/ noindex
check nishemer.ru /karta/assets/a.js noindex
check nishemer.ru /nope.html noindex 404
check nishemer.194.87.187.207.sslip.io / noindex
check nishemer.194.87.187.207.sslip.io /fakty/nisha/x/ noindex
exit $fail

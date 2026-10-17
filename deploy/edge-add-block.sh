#!/bin/bash
# Шаги 10–14: бэкап → дописать блок → validate → reload (никогда restart) → проверка соседей.
set -uo pipefail
F=/opt/edge-caddy/Caddyfile
B=/opt/edge-caddy/Caddyfile.bak-20261017-rf
HOST=nishemer.194.87.187.207.sslip.io
if grep -q "^$HOST " "$F"; then echo "блок уже есть"; exit 1; fi
cp -p "$F" "$B" && echo "backup: $B"
cat >> "$F" <<'EOF'

# RADAR «Нишемер» (/opt/rf-analytics), адрес-плейсхолдер до регистрации nishemer.ru (Э-43).
# noindex задаёт внутренний Caddy стека: страницы фактов индексируются (D27), приложение — нет.
nishemer.194.87.187.207.sslip.io {
	encode gzip
	reverse_proxy rf-analytics-caddy:8080
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "strict-origin-when-cross-origin"
	}
}
EOF
# Конфиг подаётся через stdin, а не /etc/caddy/Caddyfile: файл на хосте уже заменяли новым inode,
# и bind-монт в контейнере видит старую копию (17.10.2026 reload из неё выкинул блок Скаута на 4 мин).
if docker exec -i edge-caddy caddy validate --config /dev/stdin --adapter caddyfile < "$F" >/tmp/rf-validate.log 2>&1; then
  echo "validate: OK"
  docker exec -i edge-caddy caddy reload --config /dev/stdin --adapter caddyfile < "$F" && echo "reload: OK"
else
  echo "validate: FAIL — откат"; tail -5 /tmp/rf-validate.log
  cat "$B" > "$F"   # тот же inode: bind-монт файла не ломается
  exit 2
fi
sleep 20  # выпуск сертификата Let's Encrypt
echo "=== nishemer"
curl -s -D - -o /dev/null -m 30 "https://$HOST/" | head -12
echo "=== соседи после (до → после)"
for d in $(grep -oE '^[a-z0-9.]+ \{' "$F" | cut -d' ' -f1); do
  curl -s -o /dev/null -m 15 -w "%{http_code} $d\n" "https://$d/"
done > /root/rf-neighbors-after.txt
diff <(grep -v nishemer /root/rf-neighbors-after.txt) /root/rf-neighbors-before.txt && echo "соседи без изменений"
curl -s -o /dev/null -m 15 -w "%{http_code} elegia-tula.ru\n" https://elegia-tula.ru/

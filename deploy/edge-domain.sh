#!/bin/bash
# Блок своего домена RADAR «Нишемер» в edge-caddy на 194 (шаг «M1-домен», D37).
# Запуск — workflow edge-domain.yml: ssh root@194 "HOST=… MODE=… bash -s" < deploy/edge-domain.sh
#   MODE=dry-run  только чтение: копия Caddyfile в /tmp + блок → validate. В /opt/edge-caddy не пишет, reload нет.
#   MODE=apply    бэкап → дописать блок → validate → reload через stdin (Э-58) → проверка домена и соседей;
#                 при любом сбое — откат тем же inode и reload старого конфига.
# Никогда не делает restart edge-caddy и не трогает чужие блоки.
set -uo pipefail
HOST=${HOST:?HOST не задан}
MODE=${MODE:-dry-run}
IP=194.87.187.207
F=/opt/edge-caddy/Caddyfile
TS=$(date -u +%Y%m%d-%H%M%S)

case "$HOST" in *[!a-z0-9.-]*|"") echo "недопустимый HOST: $HOST"; exit 2;; esac
case "$MODE" in dry-run|apply) ;; *) echo "MODE: dry-run | apply"; exit 2;; esac

block() {
  cat <<EOF

# RADAR «Нишемер» (/opt/rf-analytics), свой домен (D28, D37). Добавлено edge-domain.sh $TS.
# noindex задаёт внутренний Caddy стека: на этом хосте индексируются только страницы фактов (D27).
$HOST {
	encode gzip
	reverse_proxy rf-analytics-caddy:8080
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "strict-origin-when-cross-origin"
	}
}
www.$HOST {
	redir https://$HOST{uri} permanent
}
EOF
}

validate() { docker exec -i edge-caddy caddy validate --config /dev/stdin --adapter caddyfile < "$1" > /tmp/rf-edge-validate.log 2>&1; }
reload() { docker exec -i edge-caddy caddy reload --config /dev/stdin --adapter caddyfile < "$1"; }
neighbors() {
  for d in $(grep -oE '^[a-z0-9.-]+ \{' "$1" | cut -d' ' -f1 | grep -v -F "$HOST"); do
    curl -s -o /dev/null -m 15 -w "%{http_code} $d\n" "https://$d/"
  done
}

echo "=== DNS"
for h in "$HOST" "www.$HOST"; do
  a=$(getent ahostsv4 "$h" | awk '{print $1}' | sort -u | tr '\n' ' ')
  echo "$h → ${a:-нет записи}"
  if [ "$MODE" = apply ] && [ "$a" != "$IP " ]; then echo "A-запись $h должна указывать только на $IP"; exit 3; fi
done

if grep -qE "^(www\.)?$HOST \{" "$F"; then echo "блок $HOST уже есть в $F — ничего не делаю"; exit 0; fi

if [ "$MODE" = dry-run ]; then
  T=/tmp/rf-edge-dryrun-$TS.Caddyfile
  cp "$F" "$T" && block >> "$T"
  echo "=== блок"; block
  if validate "$T"; then echo "validate: OK (dry-run, $F не изменён, reload не было)"; rc=0
  else echo "validate: FAIL"; tail -5 /tmp/rf-edge-validate.log; rc=4; fi
  rm -f "$T"
  exit $rc
fi

B=$F.bak-$TS-rf-domain
cp -p "$F" "$B" && echo "backup: $B"
neighbors "$F" > /tmp/rf-edge-before.txt
rollback() {
  echo "ОТКАТ: $1"
  cat "$B" > "$F"   # тот же inode: bind-монт файла не ломается
  reload "$F" && echo "reload старого конфига: OK"
  exit 5
}
block >> "$F"
validate "$F" || { tail -5 /tmp/rf-edge-validate.log; rollback "validate"; }
echo "validate: OK"
reload "$F" || rollback "reload"
echo "reload: OK"

echo "=== $HOST (ждём сертификат Let's Encrypt)"
code=000
for i in $(seq 1 12); do
  code=$(curl -s -o /dev/null -m 20 -w '%{http_code}' "https://$HOST/") && [ "$code" = 200 ] && break
  sleep 10
done
echo "https://$HOST/ → $code"
curl -s -D - -o /dev/null -m 20 "https://$HOST/" | grep -iE '^(HTTP|x-robots-tag)'
curl -s -D - -o /dev/null -m 20 "https://$HOST/karta/" | grep -iE '^(HTTP|x-robots-tag)'
curl -s -o /dev/null -m 20 -w "https://www.$HOST/ → %{http_code} %{redirect_url}\n" "https://www.$HOST/"

echo "=== соседи (до → после)"
neighbors "$F" > /tmp/rf-edge-after.txt
if diff /tmp/rf-edge-before.txt /tmp/rf-edge-after.txt; then echo "соседи без изменений"
else rollback "коды соседних сайтов изменились"; fi
[ "$code" = 200 ] || { echo "домен не ответил 200: блок оставлен (соседи целы), проверить сертификат"; exit 6; }

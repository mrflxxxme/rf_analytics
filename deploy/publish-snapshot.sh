#!/usr/bin/env bash
# Переключение snapshot витрин на сервере (docs/01-architecture.md, «Снимки и воспроизводимость»).
# Запуск из Actions: ssh … "SNAP=<id> bash -s" < deploy/publish-snapshot.sh
# Ожидает, что витрины уже залиты rsync'ом в /opt/rf-analytics/marts/.incoming/$SNAP/.
# Только внутри /opt/rf-analytics/marts; чужие каталоги не трогает.
set -euo pipefail

MARTS=${MARTS:-/opt/rf-analytics/marts}
KEEP=${KEEP:-6}
: "${SNAP:?SNAP не задан}"
[[ "$SNAP" =~ ^[0-9]{4}-[0-9]{2}-[0-9a-f]{7}$ ]] || { echo "плохой SNAP: $SNAP" >&2; exit 2; }

cd "$MARTS"
inc=".incoming/$SNAP"
[[ -s "$inc/manifest.json" ]] || { echo "нет $inc/manifest.json" >&2; exit 3; }
python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); assert m["snapshot"]==sys.argv[2], m["snapshot"]' \
  "$inc/manifest.json" "$SNAP"

chmod -R a+rX "$inc"

# Атомарная смена симлинка: rename(2) поверх старого. Ссылка относительная —
# api видит её внутри bind-монта /opt/rf-analytics/marts.
switch() { ln -sfn "$1" current.new; mv -T current.new current; }

if [[ -d "$SNAP" ]]; then
  # Повторный прогон того же коммита в том же месяце: current всё время указывает на целый каталог.
  mv "$inc" ".swap-$SNAP"
  switch ".swap-$SNAP"
  rm -rf -- "$SNAP"
  mv ".swap-$SNAP" "$SNAP"
else
  mv "$inc" "$SNAP"
fi
switch "$SNAP"

# Храним последние $KEEP снимков (по времени появления); текущий не удаляется никогда.
cur=$(readlink current)
mapfile -t snaps < <(ls -1dt -- [0-9][0-9][0-9][0-9]-[0-9][0-9]-* 2>/dev/null)
for s in "${snaps[@]:$KEEP}"; do
  [[ "$s" == "$cur" ]] || { echo "prune $s"; rm -rf -- "$s"; }
done

echo "current -> $cur"
ls -la "$MARTS"
python3 -c 'import json; m=json.load(open("current/manifest.json")); print(json.dumps({k: m[k] for k in ("snapshot","created_at","git_sha","methodology_version","taxonomy_version","data_date")}, ensure_ascii=False)); print(len(m["files"]), "files")'

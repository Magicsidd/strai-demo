#!/usr/bin/env bash
# Ekte Odoo 18 Community lokalt på macOS, uten Docker. Bare for demo, lytter kun på 127.0.0.1.
#
#   ./scripts/odoo_lokalt.sh installer   # PostgreSQL 16, Odoo 18-kildekode, Python-miljø og database
#   ./scripts/odoo_lokalt.sh start       # starter PostgreSQL (5433) og Odoo (8070) i forgrunnen
#
# Installerer i $ODOO_HJEM (standard ~/Projects/_odoo18), utenfor repoet. Krever Homebrew og uv.
# Databasen «strai» får modulene salg, lager, produksjon, innkjøp og CRM, uten demodata.
# Innlogging er admin / admin. Bytt passord hvis maskinen er tilgjengelig for andre.
set -euo pipefail

HJEM="${ODOO_HJEM:-$HOME/Projects/_odoo18}"
PG=/opt/homebrew/opt/postgresql@16/bin
export LC_ALL=en_US.UTF-8

skriv_konfig() {
  cat > "$HJEM/odoo.conf" <<EOF
[options]
db_host = /tmp
db_port = 5433
db_user = odoo
addons_path = $HJEM/odoo/addons,$HJEM/odoo/odoo/addons
data_dir = $HJEM/filestore
http_interface = 127.0.0.1
http_port = 8070
list_db = False
dbfilter = ^strai\$
without_demo = all
log_level = warn
EOF
}

start_pg() {
  "$PG/pg_ctl" -D "$HJEM/pgdata" -o "-p 5433 -k /tmp" -l "$HJEM/postgres.log" status >/dev/null 2>&1 || \
    "$PG/pg_ctl" -D "$HJEM/pgdata" -o "-p 5433 -k /tmp" -l "$HJEM/postgres.log" start
  until "$PG/pg_isready" -q -h /tmp -p 5433; do sleep 1; done
}

case "${1:-}" in
  installer)
    mkdir -p "$HJEM"
    HOMEBREW_NO_AUTO_UPDATE=1 brew install postgresql@16
    [ -d "$HJEM/odoo" ] || git clone --depth 1 --branch 18.0 --single-branch https://github.com/odoo/odoo.git "$HJEM/odoo"
    [ -d "$HJEM/pgdata" ] || "$PG/initdb" -D "$HJEM/pgdata" -U odoo --auth=trust -E UTF8 --locale=C
    [ -x "$HJEM/venv/bin/python" ] || uv venv "$HJEM/venv" --python 3.12
    grep -vE "^(python-ldap|gevent|greenlet)" "$HJEM/odoo/requirements.txt" > "$HJEM/krav.txt"
    PATH="$PG:$PATH" uv pip install --python "$HJEM/venv/bin/python" -r "$HJEM/krav.txt"
    skriv_konfig
    start_pg
    "$HJEM/venv/bin/python" "$HJEM/odoo/odoo-bin" -c "$HJEM/odoo.conf" -d strai \
      -i sale_management,sale_stock,mrp,purchase,crm --stop-after-init
    echo "Ferdig. Start med: $0 start"
    ;;
  start)
    skriv_konfig
    start_pg
    echo "Odoo 18 på http://127.0.0.1:8070 (admin / admin). Ctrl+C stopper Odoo."
    exec "$HJEM/venv/bin/python" "$HJEM/odoo/odoo-bin" -c "$HJEM/odoo.conf"
    ;;
  *)
    sed -n '2,9p' "$0"; exit 1 ;;
esac

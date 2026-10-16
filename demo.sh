#!/usr/bin/env bash
# Starter hele demoen: mock-Odoo (8069), seed ved tom database, backend (8000) og nettleseren.
# Ctrl+C stopper alt.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then set -a; . ./.env; set +a; fi

if [ ! -x .venv/bin/python ]; then
  echo "Lager .venv og installerer avhengigheter ..."
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
PY=.venv/bin/python

if [ ! -f katalog/elementer.json ]; then
  if ! command -v pdftotext >/dev/null 2>&1; then
    echo "Katalogen bygges fra Strai sin offentlige PDF og trenger pdftotext: brew install poppler"; exit 1
  fi
  $PY -m katalog.bygg
fi

# Velg AI: API-nøkkel, så innlogget Claude Code, ellers regelbasert reserve.
if [ -z "${AI_BACKEND:-}" ] || [ "${AI_BACKEND}" = "auto" ]; then
  if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    export AI_BACKEND=anthropic
  elif command -v claude >/dev/null 2>&1 && \
       (cd "${TMPDIR:-/tmp}" && claude -p 'Svar kun med ordet ok' --output-format json --tools "" \
         --strict-mcp-config --setting-sources "" --disable-slash-commands --no-session-persistence \
         2>/dev/null | grep -q '"is_error":false'); then
    export AI_BACKEND=claude_cli
  else
    echo "Claude svarer ikke (ingen ANTHROPIC_API_KEY, og 'claude -p' er ikke innlogget)."
    echo "Bruker regelbasert reserve. Saker merkes med det i grensesnittet."
    export AI_BACKEND=regelbasert
  fi
fi
echo "AI-backend: $AI_BACKEND"

PIDS=()
stopp() { for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap stopp EXIT INT TERM

vent_paa() {
  for _ in $(seq 1 40); do curl -sf "$1" >/dev/null 2>&1 && return 0; sleep 0.25; done
  echo "Fikk ikke svar fra $1"; exit 1
}

if [ -z "${ODOO_URL:-}" ] || [[ "${ODOO_URL}" == *"127.0.0.1:8069"* ]]; then
  echo "Starter mock-Odoo på http://127.0.0.1:8069 ..."
  $PY -m mock_odoo.server & PIDS+=($!)
  vent_paa http://127.0.0.1:8069/
  $PY -m demo.seed
fi

# Ordre og levering: ekte Odoo hvis ORDRE_ODOO_URL er satt og svarer, ellers mock-Odoo.
if [ -n "${ORDRE_ODOO_URL:-}" ]; then
  if curl -sf -o /dev/null "${ORDRE_ODOO_URL}/web/login"; then
    echo "Ordre og levering mot ekte Odoo på $ORDRE_ODOO_URL"
  else
    echo "Fikk ikke svar fra $ORDRE_ODOO_URL. Start den med ./scripts/odoo_lokalt.sh start. Bruker mock-Odoo."
    unset ORDRE_ODOO_URL ORDRE_ODOO_DB ORDRE_ODOO_USER ORDRE_ODOO_PASSWORD
  fi
fi
$PY -m demo.ordre_seed

echo "Starter backend på http://127.0.0.1:8000 ..."
$PY -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning & PIDS+=($!)
vent_paa http://127.0.0.1:8000/helse

URL=http://127.0.0.1:8000/
if [ -z "${INGEN_NETTLESER:-}" ]; then
  if command -v open >/dev/null 2>&1; then open "$URL"; elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"; fi
fi
echo "Demoen kjører på $URL  (Ctrl+C for å stoppe)"
wait

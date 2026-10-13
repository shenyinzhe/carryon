#!/bin/sh
# Entrypoint: optionally publish the server through Tailscale Funnel, then run it.
set -e
DATA=${CARRYON_DATA:-/data}
OPTS=$DATA/options.json
# opt <name>: env var CARRYON_<NAME> (standalone Docker) wins over the add-on options (Home Assistant).
opt() { python3 -c "import json,os,sys; k=sys.argv[2]; v=os.environ.get('CARRYON_'+k.upper()); print(v if v is not None else json.load(open(sys.argv[1])).get(k, ''))" "$OPTS" "$1" 2>/dev/null || true; }

case "$(opt tailscale_funnel)" in True|true|1)
  SOCK=/tmp/tailscaled.sock
  mkdir -p "$DATA/tailscale"
  # Userspace mode: no tun device or extra privileges; Funnel proxies to 127.0.0.1:8765.
  # tailscaled output can contain request paths (= the secret), so keep it out of the log.
  tailscaled --tun=userspace-networking --statedir="$DATA/tailscale" --socket=$SOCK \
    --no-logs-no-support >/dev/null 2>&1 &
  (
    ts() { tailscale --socket=$SOCK "$@"; }
    until [ -S $SOCK ]; do sleep 0.5; done
    host=$(opt tailscale_hostname)
    # First run prints a login URL here; the node key then persists in $DATA/tailscale.
    ts up --hostname="${host:-carryon}"
    ts funnel --bg 8765
    name=$(ts status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
    echo "[tailscale] public endpoint: https://$name/<secret>/mcp"
  ) &
esac

exec python -m carryon.server

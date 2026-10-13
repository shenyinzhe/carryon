#!/bin/sh
# Entrypoint: optionally publish the server through Tailscale Funnel, then run it.
set -e
OPTS=${CARRYON_DATA:-/data}/options.json
opt() { python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ''))" "$OPTS" "$1" 2>/dev/null || true; }

if [ "$(opt tailscale_funnel)" = "True" ]; then
  SOCK=/tmp/tailscaled.sock
  mkdir -p /data/tailscale
  # Userspace mode: no tun device or extra privileges; Funnel proxies to 127.0.0.1:8765.
  # tailscaled output can contain request paths (= the secret), so keep it out of the HA log.
  tailscaled --tun=userspace-networking --statedir=/data/tailscale --socket=$SOCK \
    --no-logs-no-support >/dev/null 2>&1 &
  (
    ts() { tailscale --socket=$SOCK "$@"; }
    until [ -S $SOCK ]; do sleep 0.5; done
    host=$(opt tailscale_hostname)
    # First run prints a login URL here; the node key then persists in /data/tailscale.
    ts up --hostname="${host:-carryon}"
    ts funnel --bg 8765
    name=$(ts status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
    echo "[tailscale] public endpoint: https://$name/<secret>/mcp"
  ) &
fi

exec python -m carryon.server

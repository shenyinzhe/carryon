#!/usr/bin/env bash
# Push the add-on to Home Assistant OS over SSH and (re)build it.
#   ./deploy.sh            sync files, install on first run, rebuild afterwards
#   ./deploy.sh --sync     only sync files
# Needs a `Host haos` entry in ~/.ssh/config pointing at the SSH add-on.
set -euo pipefail
cd "$(dirname "$0")/carryon"

HOST=${CARRYON_SSH_HOST:-haos}
SLUG=local_carryon

# Only the add-on folder: never ship exports/, .venv, .git or databases.
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
chmod 755 "$STAGE"  # tar carries the root dir's mode; mktemp makes it 700
cp -R Dockerfile requirements.txt run.sh DOCS.md translations carryon "$STAGE"/
# Build the local copy from source: with `image:` set, Supervisor would pull the release instead.
grep -v '^image:' config.yaml > "$STAGE/config.yaml"

# tar instead of rsync (macOS ships openrsync without --chown); the Advanced SSH
# add-on logs in as a non-root user with passwordless sudo.
COPYFILE_DISABLE=1 tar -c -C "$STAGE" --exclude __pycache__ --exclude .DS_Store . |
  ssh "$HOST" 'sudo rm -rf /addons/carryon.new && sudo mkdir /addons/carryon.new &&
    sudo tar -x --no-same-owner -C /addons/carryon.new &&
    sudo rm -rf /addons/carryon && sudo mv /addons/carryon.new /addons/carryon'
echo "synced to $HOST:/addons/carryon"
[[ "${1:-}" == "--sync" ]] && exit 0

# Non-interactive SSH sessions lack the Supervisor token that login shells get.
ssh "$HOST" "SLUG=$SLUG sh -s" <<'EOF'
set -e
export SUPERVISOR_TOKEN=$(cat /run/s6/container_environment/SUPERVISOR_TOKEN)
ha store reload >/dev/null
info=$(ha apps info "$SLUG" --raw-json)
if echo "$info" | grep -q '"version":null'; then
  echo "installing $SLUG (first build takes a few minutes)"
  ha apps install "$SLUG"
elif echo "$info" | grep -q '"update_available":true'; then
  echo "updating $SLUG (config.yaml version changed)"
  ha apps update "$SLUG"
else
  echo "rebuilding $SLUG"
  ha apps rebuild "$SLUG"
fi
ha apps info "$SLUG" --raw-json | python3 -c 'import json,sys; d=json.load(sys.stdin)["data"]; print("state:", d["state"], "version:", d["version"])'
EOF

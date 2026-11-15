#!/bin/bash
# Puts catalog.satlaspirits.com live. Run once:  bash /home/dovid/python/catalog/deploy/install.sh
# 1. installs and starts the catalog service (gunicorn on 127.0.0.1:5001) and the
#    30-minute price / on-hand refresh timer;
# 2. backs up /etc/caddy/Caddyfile, adds the catalog site, validates, and reloads
#    Caddy (a reload, not a restart: orders.satlaspirits.com stays up).
# It does not touch the orders service (mmk-web) or anything in ~/python/qbo_scripts.
set -euo pipefail
D=/home/dovid/python/catalog/deploy
sudo cp "$D/catalog-web.service" "$D/catalog-refresh.service" "$D/catalog-refresh.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now catalog-web.service catalog-refresh.timer
if ! sudo grep -q 'catalog.satlaspirits.com' /etc/caddy/Caddyfile; then
  sudo cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak-$(date +%Y%m%d-%H%M%S)"
  NEW=$(mktemp)
  { sudo cat /etc/caddy/Caddyfile; echo; cat "$D/Caddyfile.snippet"; } > "$NEW"
  sudo caddy validate --config "$NEW" --adapter caddyfile >/dev/null   # stops here if invalid
  sudo cp "$NEW" /etc/caddy/Caddyfile
  rm -f "$NEW"
  sudo systemctl reload caddy
fi
sleep 3
systemctl is-active catalog-web catalog-refresh.timer caddy mmk-web
curl -s -o /dev/null -w 'catalog (local):  %{http_code}\n' http://127.0.0.1:5001/login
curl -s -o /dev/null -m 30 -w 'catalog (public): %{http_code}\n' https://catalog.satlaspirits.com/login || true
curl -s -o /dev/null -m 15 -w 'orders  (public): %{http_code}\n' https://orders.satlaspirits.com/login || true

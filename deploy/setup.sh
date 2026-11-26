#!/usr/bin/env bash
# One-shot deploy for an Oracle Cloud Ubuntu VM (22.04/24.04, x86 or ARM).
# Puts the FastAPI app (UI + webhook, 8000) behind Caddy with HTTPS. The UI has its own login;
# Caddy adds basic auth on /webhook/*, /docs and /openapi.json.
#
# Usage, from the repo folder on the VM (with .env already filled in):
#   DEMO_USER=ld-$(openssl rand -hex 5) DEMO_PASS=$(openssl rand -base64 18) bash deploy/setup.sh
# Optional: DOMAIN=your.domain.com   (default: <public-ip>.sslip.io, free DNS that points at your IP)
set -euo pipefail

APP_DIR=$(cd "$(dirname "$0")/.." && pwd)
RUN_USER=$(whoami)
: "${DEMO_USER:?set DEMO_USER}" "${DEMO_PASS:?set DEMO_PASS}"
DOMAIN=${DOMAIN:-$(curl -s https://ifconfig.me).sslip.io}

[ -f "$APP_DIR/.env" ] || { echo "Missing $APP_DIR/.env - copy .env.example and fill in keys first"; exit 1; }
chmod 600 "$APP_DIR/.env"
grep -q "^DEMO_PASS=." "$APP_DIR/.env" || printf "DEMO_USER=%s\nDEMO_PASS=%s\n" "$DEMO_USER" "$DEMO_PASS" >> "$APP_DIR/.env"

echo "==> packages + Caddy"
sudo apt-get update -y
sudo apt-get install -y python3-venv curl gpg debian-keyring debian-archive-keyring apt-transport-https
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -y && sudo apt-get install -y caddy
fi

echo "==> python venv"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> systemd services"
write_unit() {  # name, exec
  sudo tee "/etc/systemd/system/$1.service" >/dev/null <<EOF
[Unit]
Description=LeadDesk AI $1
After=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR
ExecStart=$2
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
}
write_unit leaddesk-api "$APP_DIR/.venv/bin/uvicorn api:app --host 127.0.0.1 --port 8000"

echo "==> Caddy (HTTPS + basic auth; /health stays open)"
HASH=$(caddy hash-password --plaintext "$DEMO_PASS")
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
$DOMAIN {
	encode gzip
	# UI signs in itself (DEMO_USER/DEMO_PASS in .env); webhook + docs keep basic auth
	@protected path /webhook/* /docs /openapi.json
	basic_auth @protected {
		$DEMO_USER $HASH
	}
	reverse_proxy 127.0.0.1:8000 {
		# the app's login lockout keys on this; behind Cloudflare use {http.request.header.CF-Connecting-IP}
		header_up X-Forwarded-For {remote_host}
	}
}
EOF

echo "==> host firewall (Oracle Ubuntu images block 80/443 in iptables by default)"
RULE=(INPUT -p tcp -m multiport --dports 80,443 -m conntrack --ctstate NEW -j ACCEPT)
sudo iptables -C "${RULE[@]}" 2>/dev/null || sudo iptables -I "${RULE[@]}"
command -v netfilter-persistent >/dev/null && sudo netfilter-persistent save

sudo systemctl daemon-reload
sudo systemctl enable --now leaddesk-api
sudo systemctl restart leaddesk-api caddy

echo
echo "Done. Open https://$DOMAIN  (user: $DEMO_USER)"
echo "Also add Ingress rules for TCP 80 and 443 from 0.0.0.0/0 in the OCI console (VCN > Security List), if not done."
echo "Logs: journalctl -u leaddesk-api -f   |   journalctl -u caddy -f"

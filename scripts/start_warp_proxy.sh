#!/usr/bin/env bash
set -euo pipefail

# Install the official signed consumer WARP package in an ephemeral Linux runner.
curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg |
  sudo gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
release=$(lsb_release -cs)
printf 'deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ %s main\n' "$release" |
  sudo tee /etc/apt/sources.list.d/cloudflare-client.list >/dev/null
sudo apt-get update -qq
sudo apt-get install -y cloudflare-warp
sudo systemctl start warp-svc
sleep 3
warp-cli --accept-tos registration new
warp-cli --accept-tos mode proxy
warp-cli --accept-tos proxy port 40000
warp-cli --accept-tos connect

for attempt in 1 2 3 4 5 6; do
  if curl --proxy http://127.0.0.1:40000 --max-time 10 -fsS https://www.cloudflare.com/cdn-cgi/trace |
      grep -q '^warp=on'; then
    echo 'WARP local proxy is connected.'
    exit 0
  fi
  sleep 3
done
echo 'WARP proxy did not become ready.' >&2
exit 1

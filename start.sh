#!/bin/bash
# 공 에이전트 + Cloudflare 터널 한 번에 켜기. 사용: bash start.sh
cd "$(dirname "$0")"
PORT=${GONG_PORT:-8790}
if ! command -v cloudflared >/dev/null; then
  echo "cloudflared 설치 중..."
  ARCH=$(uname -m); [ "$ARCH" = "aarch64" ] && A=arm64 || A=amd64
  curl -sL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$A" -o cloudflared && chmod +x cloudflared
  export PATH="$PWD:$PATH"
fi
nohup python3 gong_server.py > server.log 2>&1 &
sleep 1
echo "토큰: $(cat gong_token.txt)"
echo "터널 여는 중... (아래 https://xxxx.trycloudflare.com 주소를 폰 공 설정에 넣기)"
cloudflared tunnel --url http://localhost:$PORT 2>&1 | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | head -1 &
cloudflared tunnel --url http://localhost:$PORT > tunnel.log 2>&1 &
sleep 4
grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' tunnel.log | head -1
echo "(주소가 안 보이면: grep trycloudflare tunnel.log)"

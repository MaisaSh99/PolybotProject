#!/bin/bash
set -e

echo "✅ Installing dependencies..."
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git curl unzip wget

cd ~
REPO_NAME="PolybotProject"
REPO_URL="https://github.com/MaisaSh99/PolybotProject.git"

echo "📁 Cloning or updating repo..."
if [ -d "$REPO_NAME" ]; then
  cd "$REPO_NAME"
  git stash
  git checkout main
  git pull origin main
else
  git clone -b main "$REPO_URL"
  cd "$REPO_NAME"
fi

echo "📦 Setting up Python venv..."
if [ ! -d "venv" ]; then
  echo "📦 Creating Python virtual environment..."
  python3 -m venv venv
fi
source venv/bin/activate

pip install --upgrade pip
pip install -r polybot/requirements.txt

echo "📊 Installing OpenTelemetry & Prometheus..."
bash .github/scripts/install_otelcol.sh
bash .github/scripts/install_prometheus.sh

echo "🧼 Killing old bot process..."
sudo fuser -k 8443/tcp || true

echo "⚙️ Starting Polybot prod systemd service..."
sudo cp ~/polybot-prod.service /etc/systemd/system/polybot.service
sudo systemctl daemon-reload
sudo systemctl enable polybot.service
sudo systemctl restart polybot.service

echo "🌐 Waiting for ngrok tunnel..."
max_retries=10
retry_delay=3
attempt=1
while [ $attempt -le $max_retries ]; do
  if curl -s http://localhost:4040/api/tunnels | grep -q "public_url"; then
    echo "✅ Ngrok tunnel is ready!"
    break
  fi
  echo "⏳ Waiting for ngrok... (attempt $attempt/$max_retries)"
  sleep $retry_delay
  ((attempt++))
done

if [ $attempt -gt $max_retries ]; then
  echo "❌ Ngrok tunnel not ready."
  exit 1
fi

echo "✅ Polybot Prod deployment complete!"

#!/bin/bash
set -e

echo "✅ Installing system packages..."
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git

cd ~
REPO_NAME="PolybotProject"
REPO_URL="https://github.com/MaisaSh99/PolybotProject.git"

echo "📁 Cloning or updating repo..."
if [ -d "$REPO_NAME" ]; then
    cd "$REPO_NAME"
    git reset --hard
    git clean -fd
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
chmod +x ~/install_otelcol.sh ~/install_prometheus.sh
sudo mv ~/otelcol-config.yaml /etc/otelcol/config.yaml
export OTELCOL_IP="${EC2_MONITORING_HOST:-3.147.248.148}"
sudo -E ~/install_otelcol.sh
sudo -E ~/install_prometheus.sh

echo "🧼 Killing old bot process..."
sudo fuser -k 8080/tcp || true
sudo systemctl stop polybot.service || true

echo "⚙️ Starting Polybot production systemd service..."
sudo mv ~/polybot-prod.service /etc/systemd/system/polybot.service
sudo systemctl daemon-reload
sudo systemctl enable polybot.service
sudo systemctl restart polybot.service

echo "✅ Polybot production deployment complete."

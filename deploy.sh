#!/bin/bash
set -e

echo "📦 Installing system packages..."
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git

cd ~
REPO_NAME="PolybotProject"
REPO_URL="https://github.com/MaisaSh99/PolybotProject.git"

echo "📁 Cloning or pulling latest changes..."
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

if [ ! -d "venv" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

export S3_BUCKET_NAME="maisa-polybot-images"
pip install --upgrade pip
pip install -r polybot/requirements.txt
pip install .

echo "🛑 Stopping old service and killing port 8443..."
sudo systemctl stop polybot-prod.service || true
sudo fuser -k 8443/tcp || true
sleep 2

echo "⚙️ Copying and enabling Polybot production service..."
sudo cp ~/polybot-prod.service /etc/systemd/system/polybot-prod.service
sudo systemctl daemon-reload
sudo systemctl enable polybot-prod.service
sudo systemctl restart polybot-prod.service

echo "⏱ Waiting for service to be ready..."
sleep 5

echo "📊 Checking Polybot production service status..."
sudo systemctl status polybot-prod.service || (journalctl -u polybot-prod.service -n 50 --no-pager && exit 1)

echo "✅ Polybot production service deployed and running!"

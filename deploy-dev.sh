#!/bin/bash
set -e

echo "Installing system packages..."
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git

cd ~
REPO_NAME="PolybotServicePython"
REPO_URL="https://github.com/MaisaSh99/PolybotProject.git"

echo "Cloning repo or pulling latest changes..."
if [ -d "$REPO_NAME" ]; then
    cd "$REPO_NAME"
    git pull origin dev
else
    git clone -b dev "$REPO_URL" "$REPO_NAME"
    cd "$REPO_NAME"
fi

if [ ! -d "venv" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r polybot/requirements.txt

echo "Stopping any service using port 8443..."
sudo fuser -k 8443/tcp || true

echo "Copying and enabling Polybot development service..."
sudo cp polybot-dev.service /etc/systemd/system/polybot.service
sudo systemctl daemon-reload
sudo systemctl enable polybot.service
sudo systemctl restart polybot.service

echo "Checking Polybot development service status..."
sleep 3
sudo systemctl status polybot.service || (journalctl -u polybot.service -n 50 --no-pager && exit 1)

echo "✅ Polybot development service deployed and running!"

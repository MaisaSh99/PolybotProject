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
    git checkout dev
    git pull origin dev
else
    git clone -b dev "$REPO_URL"
    cd "$REPO_NAME"
fi

if [ ! -d "venv" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

export S3_BUCKET_NAME="maisa-dev-bucket"
pip install --upgrade pip
pip install -r polybot/requirements.txt
pip install .

echo "🛑 Stopping old service and killing port 8443..."
sudo systemctl stop polybot-dev.service || true
sudo fuser -k 8443/tcp || true
sleep 2

echo "⚙️ Copying and enabling Polybot dev service..."
sudo cp ~/polybot-dev.service /etc/systemd/system/polybot-dev.service
sudo systemctl daemon-reload
sudo systemctl enable polybot-dev.service
sudo systemctl restart polybot-dev.service

echo "⏱ Waiting for service to be ready..."
sleep 5

echo "📊 Checking Polybot dev service status..."
sudo systemctl status polybot-dev.service || (journalctl -u polybot-dev.service -n 50 --no-pager && exit 1)

echo "✅ Polybot dev service deployed and running!"

#!/bin/bash

# === Configuration (Development) ===
EC2_DEV_USER=ubuntu
EC2_DEV_HOST="3.141.89.61"
KEY_PATH="/home/maisa/Desktop/m-polybot-key.pem"
REPO_URL="https://github.com/MaisaSh99/PolybotProject.git"
REPO_DIR="PolybotServicePython"

# === Start Deployment to Development ===
echo "➡️ Connecting to $EC2_DEV_USER@$EC2_DEV_HOST..."

ssh -i "$KEY_PATH" -o StrictHostKeyChecking=no $EC2_DEV_USER@$EC2_DEV_HOST << EOF
  echo "✅ Updating and installing base system packages..."
  sudo apt update
  sudo apt install -y git python3 python3-pip python3-venv

  echo "📁 Preparing repo..."
  if [ -d "$REPO_DIR" ]; then
    echo "Repo exists. Pulling latest changes..."
    cd "$REPO_DIR"
    git pull
  else
    echo "Cloning repo from GitHub..."
    git clone $REPO_URL "$REPO_DIR"
    cd "$REPO_DIR"
  fi

  echo "⚙️ Setting up polybot systemd service (Dev)..."
  sudo cp polybot-dev.service /etc/systemd/system/polybot.service

  if [ ! -d "venv" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv venv
  fi

  source venv/bin/activate
  pip install --upgrade pip
  pip install -r polybot/requirements.txt

  echo "🔁 Reloading and restarting service..."
  sudo systemctl daemon-reload
  sudo systemctl restart polybot.service
  sudo systemctl enable polybot.service

  echo "✅ Development deployment complete and service running!"
EOF

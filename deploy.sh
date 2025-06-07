#!/bin/bash

set -e

echo "🚀 Starting deployment to production..."

ENV=prod

# Ensure virtual environment exists
if [ ! -d "venv" ]; then
  echo "📦 Creating Python virtual environment..."
  python3 -m venv venv
fi

echo "🔑 Using SSH key..."
echo "$EC2_SSH_KEY" > key.pem
chmod 600 key.pem

echo "📤 Uploading project to EC2..."
scp -i key.pem -o StrictHostKeyChecking=no -r . ubuntu@$EC2_IP:/home/ubuntu/polybot

echo "📦 Deploying on EC2..."
ssh -i key.pem -o StrictHostKeyChecking=no ubuntu@$EC2_IP << 'EOF'
  set -e
  cd /home/ubuntu/polybot

  echo "✅ Installing dependencies..."
  sudo apt update
  sudo apt install -y git python3 python3-pip python3-venv curl unzip wget

  echo "📁 Cloning or updating repo..."
  git reset --hard
  git checkout prod
  git pull origin prod

  echo "📦 Setting up Python venv..."
  if [ ! -d "venv" ]; then
    python3 -m venv venv
  fi
  source venv/bin/activate
  pip install --upgrade pip
  pip install -r polybot/requirements.txt
  pip install boto3

  echo "📊 Installing OpenTelemetry & Prometheus..."
  chmod +x .github/scripts/install_otelcol.sh
  chmod +x .github/scripts/install_prometheus.sh
  sudo .github/scripts/install_otelcol.sh
  sudo .github/scripts/install_prometheus.sh

  echo "🧼 Killing old bot process..."
  sudo systemctl stop polybot-prod.service || true

  echo "⚙️ Starting Polybot prod systemd service..."
  sudo systemctl daemon-reexec
  sudo systemctl restart polybot-prod.service
  sudo systemctl enable polybot-prod.service

  echo "🌐 Launching Ngrok in background on port 8443..."
  nohup ./ngrok http 8443 > ngrok.log 2>&1 &

  echo "📜 Ngrok is launching. Check ngrok.log for public URL."
EOF

echo "✅ Deployment to production completed!"

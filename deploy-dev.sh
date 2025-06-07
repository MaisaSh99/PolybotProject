#!/bin/bash
set -e

echo "🚀 Starting development deployment..."

EC2_IP="${EC2_DEV_HOST}"
EC2_USER="${EC2_DEV_USER}"
REPO="MaisaSh99/PolybotProject"
SERVICE_FILE="polybot-dev.service"

echo "📦 Creating deployment package..."

scp -i key.pem -o StrictHostKeyChecking=no $SERVICE_FILE $EC2_USER@$EC2_IP:~/
scp -i key.pem -o StrictHostKeyChecking=no otelcol-config.yaml $EC2_USER@$EC2_IP:~/
scp -i key.pem -o StrictHostKeyChecking=no .github/scripts/install_otelcol.sh $EC2_USER@$EC2_IP:~/
scp -i key.pem -o StrictHostKeyChecking=no .github/scripts/install_prometheus.sh $EC2_USER@$EC2_IP:~/

ssh -i key.pem -o StrictHostKeyChecking=no $EC2_USER@$EC2_IP << 'EOF'
  set -e

  echo "✅ Installing dependencies..."
  sudo apt update
  sudo apt install -y git python3 python3-pip python3-venv wget curl unzip

  echo "📁 Cloning or updating repo..."
  cd /home/ubuntu
  if [ -d "PolybotProject" ]; then
    cd PolybotProject
    git reset --hard
    git clean -fd
    git checkout dev
    git pull origin dev
  else
    git clone https://github.com/MaisaSh99/PolybotProject.git
    cd PolybotProject
    git checkout dev
  fi

  echo "📦 Setting up Python venv..."
  if [ ! -d "venv" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv venv
  fi
  source venv/bin/activate
  export S3_BUCKET_NAME="maisa-dev-bucket"
  pip install --upgrade pip
  pip install -r polybot/requirements.txt
  pip install boto3

  echo "📊 Installing OpenTelemetry & Prometheus..."
  chmod +x ~/install_otelcol.sh ~/install_prometheus.sh
  sudo mkdir -p /etc/otelcol
  sudo mv ~/otelcol-config.yaml /etc/otelcol/config.yaml
  export OTELCOL_IP="$EC2_IP"
  sudo -E ~/install_otelcol.sh
  export OTELCOL_IP="10.0.1.17"
  sudo -E ~/install_prometheus.sh

  echo "🧼 Killing old service if running..."
  sudo fuser -k 5000/tcp || true
  sudo systemctl stop polybot-dev.service || true

  echo "⚙️ Enabling and starting polybot-dev.service"
  sudo mv ~/polybot-dev.service /etc/systemd/system/polybot-dev.service
  sudo systemctl daemon-reload
  sudo systemctl enable polybot-dev.service
  sudo systemctl restart polybot-dev.service

  echo "✅ Development Polybot deployment complete."
EOF

#!/bin/bash
set -e

echo "📦 Installing OpenTelemetry Collector..."

cd /tmp

# Download and extract OpenTelemetry Collector
wget -q https://github.com/open-telemetry/opentelemetry-collector-releases/releases/latest/download/otelcol-linux-amd64.tar.gz
tar -xzf otelcol-linux-amd64.tar.gz
sudo mv otelcol /usr/local/bin/otelcol

# Create config directory
sudo mkdir -p /etc/otelcol

# Copy config (should be uploaded by deploy script or GitHub Actions)
sudo cp ~/otelcol-config.yaml /etc/otelcol/config.yaml

# Create systemd service
sudo tee /etc/systemd/system/otelcol.service > /dev/null <<EOF
[Unit]
Description=OpenTelemetry Collector
After=network.target

[Service]
ExecStart=/usr/local/bin/otelcol --config /etc/otelcol/config.yaml
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Reload and start otelcol
sudo systemctl daemon-reload
sudo systemctl enable otelcol
sudo systemctl restart otelcol

echo "✅ OpenTelemetry Collector installed and running!"

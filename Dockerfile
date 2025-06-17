FROM python:3.10-slim
WORKDIR /app

# Update system packages and install security updates
RUN apt-get update && apt-get upgrade -y && apt-get clean && rm -rf /var/lib/apt/lists/*

# Upgrade pip and setuptools to fix security vulnerabilities
RUN pip install --upgrade pip setuptools>=78.1.1

COPY polybot/requirements.txt .
RUN pip install -r requirements.txt

COPY . .
ENV PYTHONPATH=/app
CMD ["python3", "polybot/app.py"]
FROM python:3.10-slim
WORKDIR /app
COPY polybot/requirements.txt .
RUN pip install -r requirements.txt
COPY . .
ENV PYTHONPATH=/app
CMD ["python3", "polybot/app.py"]

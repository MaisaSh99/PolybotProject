import flask
from flask import request
import os
from bot import ImageProcessingBot

app = flask.Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
BOT_APP_URL = os.environ['BOT_APP_URL']
YOLO_SERVICE_URL = os.environ['YOLO_SERVICE_URL']

# ✅ Move bot initialization to global scope
bot = ImageProcessingBot(TELEGRAM_BOT_TOKEN, BOT_APP_URL, yolo_service_url=YOLO_SERVICE_URL)

@app.route('/', methods=['GET'])
def index():
    return 'Ok'

@app.route('/health', methods=['GET'])
def health():
    return 'ok', 200

@app.route(f'/{TELEGRAM_BOT_TOKEN}/', methods=['POST'])
def webhook():
    req = request.get_json()
    bot.handle_message(req['message'])
    return 'Ok'

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8443)

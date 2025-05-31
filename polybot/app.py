import os
import flask
from flask import request
from loguru import logger
from polybot.bot import ImageProcessingBot

app = flask.Flask(__name__)

# Load environment variables
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
BOT_APP_URL = os.environ.get('BOT_APP_URL')
YOLO_SERVICE_URL = os.environ.get('YOLO_SERVICE_URL')

# Initialize the bot
bot = ImageProcessingBot(TELEGRAM_BOT_TOKEN, BOT_APP_URL, YOLO_SERVICE_URL)

@app.route('/', methods=['GET'])
def index():
    return 'OK'

@app.route(f'/{TELEGRAM_BOT_TOKEN}/', methods=['POST'])
def webhook():
    req = request.get_json()
    msg = req.get('message', {})
    logger.info(f"📨 Webhook received: message_id={msg.get('message_id')}, chat_id={msg.get('chat', {}).get('id')}")
    bot.handle_message(msg)
    return 'OK'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8443)

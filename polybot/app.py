import flask
from flask import request
import os
from polybot.bot import Bot, QuoteBot, ImageProcessingBot

app = flask.Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
BOT_APP_URL = os.environ['BOT_APP_URL']
YOLO_SERVICE_URL = os.environ['YOLO_SERVICE_URL']

# ✅ Always initialize the bot globally
bot = ImageProcessingBot(TELEGRAM_BOT_TOKEN, BOT_APP_URL, YOLO_SERVICE_URL)

@app.route('/', methods=['GET'])
def index():
    return 'Ok'

@app.route(f'/{TELEGRAM_BOT_TOKEN}/', methods=['POST'])
def webhook():
    req = request.get_json()
    # ✅ Add basic check to avoid double-calling
    if 'message' in req:
        bot.handle_message(req['message'])
    return 'Ok'

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8443)

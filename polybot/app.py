import flask
from flask import request
import os
from polybot.bot import ImageProcessingBot

app = flask.Flask(__name__)

# ✅ Read environment variables
TELEGRAM_BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
BOT_APP_URL = os.environ.get('BOT_APP_URL')
YOLO_SERVICE_URL = os.environ['YOLO_SERVICE_URL']

# ✅ Init bot
bot = ImageProcessingBot(TELEGRAM_BOT_TOKEN, BOT_APP_URL, YOLO_SERVICE_URL)

processed_update_ids = set()

@app.route('/', methods=['GET'])
def index():
    return 'Ok'

@app.route('/health', methods=['GET'])
def health():
    return 'ok', 200

# ✅ Route must match Telegram webhook URL
@app.route(f'/{TELEGRAM_BOT_TOKEN}/', methods=['POST'])
def webhook():
    req = request.get_json()
    update_id = req.get("update_id")

    if update_id in processed_update_ids:
        print(f"🔁 Skipping duplicate update: {update_id}")
        return 'Duplicate ignored', 200

    print(f"📩 Processing new update: {update_id}")
    processed_update_ids.add(update_id)

    if 'message' in req:
        bot.handle_message(req['message'])

    return 'Ok', 200

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8443)
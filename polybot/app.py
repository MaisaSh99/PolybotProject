import flask
from flask import request
import os
from polybot.bot import ImageProcessingBot

app = flask.Flask(__name__)

# ✅ Read core environment variables
TELEGRAM_BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
YOLO_SERVICE_URL = os.environ['YOLO_SERVICE_URL']
TYPE_ENV = os.environ.get('TYPE_ENV', 'prod').lower()

# ✅ Dynamically determine the BOT_APP_URL based on TYPE_ENV
if TYPE_ENV == 'dev':
    BOT_APP_URL = 'https://maisadev.fursa.click'
else:
    BOT_APP_URL = 'https://maisaprod.fursa.click'

# ✅ Init the bot with the resolved URL
bot = ImageProcessingBot(TELEGRAM_BOT_TOKEN, BOT_APP_URL, YOLO_SERVICE_URL)

# ✅ Optional: Port configuration (default 8443)
PORT = int(os.environ.get('BOT_PORT', 8443))

# ✅ Track processed update_ids during runtime
processed_update_ids = set()

@app.route('/', methods=['GET'])
def index():
    return 'Ok'

@app.route('/health', methods=['GET'])
def health():
    return 'ok', 200

# ✅ Route must match Telegram webhook path
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
    app.run(host='0.0.0.0', port=PORT)

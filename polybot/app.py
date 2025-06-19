import flask
from flask import request
import os
from polybot.bot import ImageProcessingBot
import requests

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


@app.route('/yolo-result', methods=['POST'])
def receive_yolo_result():
    """Endpoint to receive YOLO processing results"""
    try:
        data = request.get_json()

        if not data:
            return 'No data provided', 400

        chat_id = data.get('chat_id')
        status = data.get('status')
        labels = data.get('labels', [])
        prediction_id = data.get('prediction_id', 'unknown')
        error_message = data.get('error')

        if not chat_id:
            return 'chat_id is required', 400

        print(f"📩 Received YOLO result for prediction {prediction_id[:8]}")
        print(f"Status: {status}, Labels: {labels}")

        if status == 'success':
            if labels:
                result_text = f"✅ Detection complete!\nDetected objects: {', '.join(labels)}"
            else:
                result_text = "✅ Detection complete!\nNo objects detected."

            bot.send_text(chat_id, result_text)

            # Try to get the processed image from YOLO service
            try:
                image_response = requests.get(
                    f"{YOLO_SERVICE_URL}/prediction/{prediction_id}/image",
                    headers={"Accept": "image/jpeg"},
                    timeout=10
                )

                if image_response.status_code == 200:
                    # Save temporarily and send
                    temp_image_path = f"/tmp/yolo_result_{prediction_id[:8]}.jpg"
                    with open(temp_image_path, 'wb') as f:
                        f.write(image_response.content)

                    bot.send_photo(chat_id, temp_image_path)

                    # Clean up
                    os.remove(temp_image_path)
                else:
                    print(f"⚠️ Could not retrieve processed image: {image_response.status_code}")

            except Exception as e:
                print(f"⚠️ Failed to retrieve processed image: {e}")

        elif status == 'error':
            bot.send_text(chat_id, f"❌ Detection failed: {error_message or 'Unknown error'}")
        else:
            bot.send_text(chat_id, f"ℹ️ Detection status: {status}")

        return 'OK', 200

    except Exception as e:
        print(f"❌ Error processing YOLO result: {e}")
        return 'Internal server error', 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8443)
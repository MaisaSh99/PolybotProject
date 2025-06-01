import os
import time
import threading
import requests
from datetime import datetime
from telebot import TeleBot
from telebot.types import InputFile
from polybot.img_proc import Img
from loguru import logger
import boto3

# ✅ Skip token validation during testing (for unit tests)
if os.getenv("SKIP_TELEGRAM_TOKEN_VALIDATION") == "1":
    import telebot.util
    telebot.util.validate_token = lambda token: True

class Bot:
    def __init__(self, token, telegram_chat_url):
        self.telegram_bot_client = TeleBot(token)
        self.telegram_bot_client.remove_webhook()
        time.sleep(0.5)
        self.telegram_bot_client.set_webhook(url=f'{telegram_chat_url}/{token}/', timeout=60)
        logger.info(f"🤖 Telegram Bot initialized: {self.telegram_bot_client.get_me()}")

        self.bucket_name = os.getenv('S3_BUCKET_NAME') or 'maisa-polybot-images'
        self.s3 = boto3.client('s3', region_name='us-east-2')

        try:
            self.s3.head_bucket(Bucket=self.bucket_name)
            logger.info(f"✅ Connected to S3 bucket: {self.bucket_name}")
        except Exception as e:
            logger.error(f"❌ Cannot access S3 bucket: {e}")
            raise

    def send_text(self, chat_id, text):
        self.telegram_bot_client.send_message(chat_id, text)

    def send_photo(self, chat_id, img_path):
        if not os.path.exists(img_path):
            logger.error(f"❌ Image not found: {img_path}")
            self.send_text(chat_id, "Image not found.")
            return
        self.telegram_bot_client.send_photo(chat_id, InputFile(img_path))

    def upload_to_s3(self, local_path, s3_key):
        if not os.path.exists(local_path):
            logger.error(f"❌ Local file not found: {local_path}")
            return
        try:
            self.s3.upload_file(local_path, self.bucket_name, s3_key)
            logger.info(f"✅ Uploaded to S3: {s3_key}")
        except Exception as e:
            logger.exception(f"❌ S3 upload failed: {e}")

class ImageProcessingBot(Bot):
    def __init__(self, token, telegram_chat_url, yolo_service_url='http://localhost:8080'):
        super().__init__(token, telegram_chat_url)
        self.yolo_service_url = yolo_service_url
        self.processed_messages = set()
        self.processing_lock = threading.Lock()

    def handle_message(self, msg):
        chat_id = msg['chat']['id']
        message_id = msg.get('message_id')

        if message_id is None:
            logger.warning("⚠️ No message_id, skipping deduplication")
            return

        unique_key = f"{chat_id}:{message_id}"
        if unique_key in self.processed_messages:
            logger.warning(f"⚠️ Duplicate message received: {unique_key}, skipping.")
            return

        self.processed_messages.add(unique_key)
        if len(self.processed_messages) > 1000:
            self.processed_messages = set(list(self.processed_messages)[-500:])

        logger.info(f"📩 Processing new message: {unique_key}")

        if 'text' in msg:
            text = msg['text'].strip().lower()
            if text == 'hi':
                self.send_text(chat_id, "Hi, how can I help you?")
                return
            elif text == 'test s3':
                self.test_s3_connection(chat_id)
                return

        if 'photo' not in msg:
            self.send_text(chat_id, "📷 Please send a photo with a caption like 'yolo'")
            return

        try:
            photo_path = self.download_user_photo(msg)
        except Exception as e:
            logger.error(f"❌ Photo download failed: {e}")
            self.send_text(chat_id, "❌ Failed to download image.")
            return

        caption = msg.get('caption', '').strip().lower()
        if not caption:
            self.send_text(chat_id, "📌 Please add a filter name like 'yolo'.")
            return

        if caption == 'yolo':
            if self.processing_lock.acquire(blocking=False):
                try:
                    self.apply_yolo(chat_id, photo_path)
                finally:
                    self.processing_lock.release()
            else:
                logger.warning("⚠️ YOLO already running, skipping.")
                self.send_text(chat_id, "⏳ Processing another image. Please wait.")
        else:
            self.send_text(chat_id, f"❓ Unknown caption '{caption}'. Try 'yolo'.")

    def download_user_photo(self, msg):
        file_id = msg['photo'][-1]['file_id']
        file_info = self.telegram_bot_client.get_file(file_id)
        data = self.telegram_bot_client.download_file(file_info.file_path)

        folder = file_info.file_path.split('/')[0]
        os.makedirs(folder, exist_ok=True)
        full_path = os.path.abspath(file_info.file_path)

        with open(full_path, 'wb') as f:
            f.write(data)

        logger.info(f"✅ Image saved to: {full_path}")
        return full_path

    def apply_yolo(self, chat_id, photo_path):
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

        try:
            with open(photo_path, 'rb') as f:
                files = {'file': (os.path.basename(photo_path), f, 'image/jpeg')}
                headers = {'x-user-id': str(chat_id)}
                response = requests.post(f"{self.yolo_service_url}/predict", files=files, headers=headers)
                logger.info(f"📡 YOLO response: {response.status_code}")
                response.raise_for_status()
                result = response.json()

            labels = result.get("labels", [])
            if labels:
                self.send_text(chat_id, "✅ Objects detected:\n" + "\n".join(sorted(set(labels))))
            else:
                self.send_text(chat_id, "🤖 No objects detected.")

            prediction_uid = result.get("prediction_uid")
            if prediction_uid:
                image_url = f"{self.yolo_service_url}/prediction/{prediction_uid}/image"
                pred_response = requests.get(image_url)
                if pred_response.status_code == 200:
                    pred_path = f"/tmp/predicted_{timestamp}.jpg"
                    with open(pred_path, 'wb') as f:
                        f.write(pred_response.content)
                    s3_key = f"predicted/{chat_id}/{timestamp}_predicted.jpg"
                    self.upload_to_s3(pred_path, s3_key)
                    self.send_photo(chat_id, pred_path)
                    os.remove(pred_path)

            os.remove(photo_path)

        except Exception as e:
            logger.exception(f"❌ YOLO processing failed: {e}")
            self.send_text(chat_id, "❌ Failed to process image with YOLO.")

    def test_s3_connection(self, chat_id):
        try:
            test_path = "/tmp/s3_test.txt"
            with open(test_path, 'w') as f:
                f.write("Hello S3")
            s3_key = f"test/test_{datetime.now().strftime('%Y%m%d%H%M%S')}.txt"
            self.upload_to_s3(test_path, s3_key)
            os.remove(test_path)
            self.send_text(chat_id, "✅ S3 test upload successful.")
        except Exception as e:
            logger.error(f"❌ S3 test failed: {e}")
            self.send_text(chat_id, "❌ S3 test failed.")

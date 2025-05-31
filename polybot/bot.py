import threading
import telebot
from loguru import logger
import os
import time
import requests
from telebot.types import InputFile
from polybot.img_proc import Img
import boto3
from datetime import datetime

class Bot:
    def __init__(self, token, telegram_chat_url):
        self.telegram_bot_client = telebot.TeleBot(token)
        self.telegram_bot_client.remove_webhook()
        time.sleep(0.5)
        self.telegram_bot_client.set_webhook(url=f'{telegram_chat_url}/{token}/', timeout=60)
        logger.info(f'Telegram Bot information\n\n{self.telegram_bot_client.get_me()}')

        self.bucket_name = os.getenv('S3_BUCKET_NAME') or 'maisa-polybot-images'
        logger.info(f"🪳 Using S3 bucket: {self.bucket_name}")
        self.s3 = boto3.client('s3', region_name='us-east-2')

        try:
            self.s3.head_bucket(Bucket=self.bucket_name)
            logger.info(f"✅ Successfully connected to S3 bucket: {self.bucket_name}")
        except Exception as e:
            logger.error(f"❌ Failed to access S3 bucket {self.bucket_name}: {e}")
            raise

    def send_text(self, chat_id, text):
        self.telegram_bot_client.send_message(chat_id, text)

    def send_photo(self, chat_id, img_path):
        if not os.path.exists(img_path):
            raise RuntimeError("Image path doesn't exist")
        self.telegram_bot_client.send_photo(chat_id, InputFile(img_path))

    def upload_to_s3(self, local_path, s3_path):
        logger.info(f"📄 Uploading {local_path} to s3://{self.bucket_name}/{s3_path}")

        try:
            if not os.path.exists(local_path):
                logger.error(f"❌ File not found: {local_path}")
                return

            file_size = os.path.getsize(local_path)
            logger.info(f"📏 File size: {file_size} bytes")

            if file_size == 0:
                logger.error(f"❌ File is empty: {local_path}")
                return

            self.s3.upload_file(local_path, self.bucket_name, s3_path)
            logger.info("✅ Upload successful")

        except Exception as e:
            logger.error(f"❌ Upload to S3 failed: {e}")
            raise

class ImageProcessingBot(Bot):
    def __init__(self, token, telegram_chat_url, yolo_service_url='http://localhost:8080'):
        super().__init__(token, telegram_chat_url)
        self.yolo_service_url = yolo_service_url

    def handle_message(self, msg):
        chat_id = msg['chat']['id']
        logger.info(f'Incoming message: {msg}')

        if 'text' in msg:
            text = msg['text'].strip().lower()
            if text == 'hi':
                self.send_text(chat_id, "Hi, how can I help you?")
                return
            elif text == 'test s3':
                self.test_s3_connection(chat_id)
                return

        if 'photo' not in msg:
            self.send_text(chat_id, "Please send a photo with a caption indicating the filter to apply.")
            return

        photo_path = self.download_user_photo(msg)
        caption = msg.get('caption', '').strip().lower()
        if not caption:
            self.send_text(chat_id, "You need to choose a filter.")
            return

        if caption == 'yolo':
            self.apply_yolo(msg, photo_path)
        else:
            self.send_text(chat_id, f"Unknown caption '{caption}'. Try 'yolo'.")

    def download_user_photo(self, msg):
        try:
            file_info = self.telegram_bot_client.get_file(msg['photo'][-1]['file_id'])
            data = self.telegram_bot_client.download_file(file_info.file_path)

            folder = file_info.file_path.split('/')[0]
            os.makedirs(folder, exist_ok=True)
            full_path = file_info.file_path

            with open(full_path, 'wb') as f:
                f.write(data)

            logger.info(f"✅ Saved image: {full_path}")
            return full_path
        except Exception as e:
            logger.error(f"❌ Download failed: {e}")
            raise

    def apply_yolo(self, msg, photo_path):
        try:
            chat_id = msg['chat']['id']
            telegram_user_id = str(msg.get('from', {}).get('id', chat_id))
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

            s3_key = f"original/{telegram_user_id}/{timestamp}.jpg"
            self.upload_to_s3(photo_path, s3_key)

            with open(photo_path, 'rb') as f:
                files = {'file': (os.path.basename(photo_path), f, 'image/jpeg')}
                headers = {'X-User-ID': telegram_user_id}

                response = requests.post(f"{self.yolo_service_url}/predict", files=files, headers=headers)
                logger.info(f"YOLO response: {response.status_code} {response.text}")
                response.raise_for_status()
                result = response.json()

            labels = result.get("labels", [])
            if labels:
                self.send_text(chat_id, "Detected objects:\n" + "\n".join(labels))
            else:
                self.send_text(chat_id, "No objects detected.")

            prediction_uid = result.get("prediction_uid")
            if prediction_uid:
                image_url = f"{self.yolo_service_url}/prediction/{prediction_uid}/image"
                pred_image = requests.get(image_url)

                if pred_image.status_code == 200:
                    pred_path = f"/tmp/predicted_{timestamp}.jpg"
                    with open(pred_path, 'wb') as f:
                        f.write(pred_image.content)

                    pred_s3_key = f"predicted/{telegram_user_id}/{timestamp}_predicted.jpg"
                    self.upload_to_s3(pred_path, pred_s3_key)
                    self.send_photo(chat_id, pred_path)
                    os.remove(pred_path)
                    os.remove(photo_path)

        except Exception as e:
            logger.error(f"❌ YOLO failed: {e}")
            self.send_text(chat_id, "Failed to process image with YOLO.")

    def test_s3_connection(self, chat_id):
        try:
            path = "/tmp/test_s3.txt"
            with open(path, 'w') as f:
                f.write("S3 connection test")
            key = f"test/test_{datetime.now().strftime('%Y%m%d%H%M%S')}.txt"
            self.upload_to_s3(path, key)
            os.remove(path)
            self.send_text(chat_id, "✅ S3 upload test successful.")
        except Exception as e:
            logger.error(f"S3 test failed: {e}")
            self.send_text(chat_id, f"❌ S3 test failed: {e}")

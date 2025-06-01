import os
import time
import threading
import requests
from datetime import datetime
from loguru import logger
from telebot import TeleBot
from telebot.types import InputFile
import boto3
import re  # ✅ Added for caption normalization

from polybot.img_proc import Img

# ✅ Optional: Skip token validation in tests
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

        # ✅ Optional: Skip S3 during test
        if os.getenv("SKIP_S3") == "1":
            self.s3 = None
            logger.info("🚫 S3 initialization skipped (SKIP_S3=1)")
        else:
            self.s3 = boto3.client('s3', region_name='us-east-2')
            try:
                self.s3.head_bucket(Bucket=self.bucket_name)
                logger.info(f"✅ Connected to S3 bucket: {self.bucket_name}")
            except Exception as e:
                logger.error(f"❌ Cannot access S3 bucket: {e}")
                raise

    def send_text(self, chat_id, text):
        self.telegram_bot_client.send_message(chat_id, text)

    def send_text_with_quote(self, chat_id, text, quoted_msg_id):
        self.telegram_bot_client.send_message(chat_id, text, reply_to_message_id=quoted_msg_id)

    def send_photo(self, chat_id, img_path):
        if not os.path.exists(img_path):
            logger.error(f"❌ Image not found: {img_path}")
            self.send_text(chat_id, "Image not found.")
            return
        self.telegram_bot_client.send_photo(chat_id, InputFile(img_path))

    def upload_to_s3(self, local_path, s3_key):
        if not self.s3:
            logger.info("📦 Skipping S3 upload (SKIP_S3 enabled)")
            return
        if not os.path.exists(local_path):
            logger.error(f"❌ Local file not found: {local_path}")
            return
        try:
            self.s3.upload_file(local_path, self.bucket_name, s3_key)
            logger.info(f"✅ Uploaded to S3: {s3_key}")
        except Exception as e:
            logger.exception(f"❌ S3 upload failed: {e}")

    def is_current_msg_photo(self, msg):
        return 'photo' in msg

    def download_user_photo(self, msg):
        if not self.is_current_msg_photo(msg):
            raise RuntimeError(f'Message content of type "photo" expected')
        file_info = self.telegram_bot_client.get_file(msg['photo'][-1]['file_id'])
        data = self.telegram_bot_client.download_file(file_info.file_path)
        folder_name = file_info.file_path.split('/')[0]
        os.makedirs(folder_name, exist_ok=True)
        full_path = os.path.abspath(file_info.file_path)
        with open(full_path, 'wb') as f:
            f.write(data)
        logger.info(f"✅ Image saved to: {full_path}")
        return full_path


class ImageProcessingBot(Bot):
    def __init__(self, token, telegram_chat_url, yolo_service_url='http://localhost:8080'):
        super().__init__(token, telegram_chat_url)
        self.yolo_service_url = yolo_service_url
        self.processing_lock = threading.Lock()
        self.media_groups = {}

    def handle_message(self, msg):
        chat_id = msg['chat']['id']
        logger.info(f'Incoming message: {msg}')

        if 'text' in msg and msg['text'].strip().lower() == 'hi':
            self.send_text(chat_id, "Hi, how can I help you?")
            return

        if self.is_current_msg_photo(msg):
            try:
                photo_path = self.download_user_photo(msg)
            except Exception as e:
                logger.error(f"❌ Photo download failed: {e}")
                self.send_text(chat_id, "❌ Failed to download image.")
                return

            media_group_id = msg.get('media_group_id')

            # ✅ Normalize and log caption early!
            raw_caption = msg.get('caption', '')
            logger.info(f"📌 Raw caption: '{raw_caption}'")
            caption = re.sub(r'[^a-zA-Z0-9 ]', '', raw_caption).strip().lower()
            logger.info(f"📌 Normalized caption: '{caption}'")

            if media_group_id:
                ...
                # (leave this unchanged)

            if not caption:
                self.send_text(chat_id, "📌 Please add a filter name like 'blur', 'rotate', 'yolo', etc.")
                return

            # ✅ Now this check will work correctly
            if caption == 'yolo':
                if self.processing_lock.acquire(blocking=False):
                    try:
                        self.apply_yolo(chat_id, photo_path)
                    finally:
                        self.processing_lock.release()
                else:
                    self.send_text(chat_id, "⏳ Already processing an image. Please wait.")
                return

            self.apply_filter_from_caption(chat_id, photo_path, caption)
            return

        self.send_text(chat_id, "📷 Please send a photo with a caption indicating the filter to apply.")

    def _process_media_group(self, group_id):
        group = self.media_groups.pop(group_id, None)
        if not group:
            return
        chat_id = group['chat_id']
        photos = group['photos']
        filter_name = group['filter']
        if not filter_name:
            self.send_text(chat_id, "You need to choose a filter.")
            return
        if filter_name == 'concat':
            if len(photos) != 2:
                self.send_text(chat_id, "The 'concat' filter works only on two photos.")
                return
            self._apply_concat(chat_id, photos)
        else:
            self.send_text(chat_id, f"Unknown group filter '{filter_name}'.")

    def _apply_concat(self, chat_id, photos):
        try:
            img1 = Img(photos[0])
            img2 = Img(photos[1])
            if len(img1.data) == len(img2.data):
                img1.concat(img2, direction='horizontal')
            elif len(img1.data[0]) == len(img2.data[0]):
                img1.concat(img2, direction='vertical')
            else:
                self.send_text(chat_id, "Images have incompatible dimensions for concatenation.")
                return
            result_path = img1.save_img()
            self.upload_to_s3(result_path, f"filtered/{chat_id}/{os.path.basename(result_path)}")
            self.send_photo(chat_id, str(result_path))
        except Exception as e:
            logger.error(f"Concat error: {e}")
            self.send_text(chat_id, "Concat failed. Ensure images are compatible.")

    def apply_filter_from_caption(self, chat_id, photo_path, caption):
        img = Img(photo_path)
        try:
            if caption == 'blur':
                img.blur()
            elif caption == 'rotate':
                img.rotate()
            elif caption in ('salt and pepper', 'saltnpepper', 'salt_n_pepper'):
                img.salt_n_pepper()
            elif caption == 'contour':
                img.contour()
            elif caption == 'segment':
                img.segment()
            else:
                self.send_text(chat_id, f"❌ Unknown filter '{caption}'.")
                return
            filtered_path = img.save_img()
            self.upload_to_s3(filtered_path, f"filtered/{chat_id}/{os.path.basename(filtered_path)}")
            self.send_photo(chat_id, str(filtered_path))
        except Exception as e:
            logger.error(f"Error applying filter '{caption}': {e}")
            self.send_text(chat_id, "❌ An error occurred while applying the filter.")

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

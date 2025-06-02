import string
import threading
import telebot
from loguru import logger
import os
import time
import requests
import boto3
from telebot.types import InputFile
from polybot.img_proc import Img
from datetime import datetime, timezone


class Bot:
    def __init__(self, token, telegram_chat_url):
        self.telegram_bot_client = telebot.TeleBot(token)
        self.telegram_bot_client.remove_webhook()
        time.sleep(0.5)
        self.telegram_bot_client.set_webhook(url=f'{telegram_chat_url}/{token}/', timeout=60)
        logger.info(f'Telegram Bot information\n\n{self.telegram_bot_client.get_me()}')

    def send_text(self, chat_id, text):
        self.telegram_bot_client.send_message(chat_id, text)

    def send_text_with_quote(self, chat_id, text, quoted_msg_id):
        self.telegram_bot_client.send_message(chat_id, text, reply_to_message_id=quoted_msg_id)

    def is_current_msg_photo(self, msg):
        return 'photo' in msg

    def download_user_photo(self, msg):
        if not self.is_current_msg_photo(msg):
            raise RuntimeError("Message content of type 'photo' expected")

        try:
            file_info = self.telegram_bot_client.get_file(msg['photo'][-1]['file_id'])
            data = self.telegram_bot_client.download_file(file_info.file_path)
            folder_name = file_info.file_path.split('/')[0]

            if not os.path.exists(folder_name):
                os.makedirs(folder_name)

            with open(file_info.file_path, 'wb') as photo:
                photo.write(data)

            return file_info.file_path  # ✅ Inside try block

        except OSError as e:
            logger.error(f"File saving error: {e}")
            self.send_text(msg['chat']['id'], "Something went wrong, try again please.")
            raise

    def send_photo(self, chat_id, img_path):
        if not os.path.exists(img_path):
            raise RuntimeError("Image path doesn't exist")

        self.telegram_bot_client.send_photo(chat_id, InputFile(img_path))

    def handle_message(self, msg):
        logger.info(f'Incoming message: {msg}')
        self.send_text(msg['chat']['id'], f'Your original message: {msg["text"]}')


class QuoteBot(Bot):
    def handle_message(self, msg):
        logger.info(f'Incoming message: {msg}')
        if msg["text"] != "Please don't quote me":
            self.send_text_with_quote(msg['chat']['id'], msg["text"], quoted_msg_id=msg["message_id"])


class ImageProcessingBot(Bot):
    def __init__(self, token, telegram_chat_url, yolo_service_url='http://localhost:8080'):
        super().__init__(token, telegram_chat_url)
        self.media_groups = {}
        self.yolo_service_url = yolo_service_url

    def upload_file_to_s3(self, local_path, bucket_name, s3_key):
        logger.info("\U0001F4E6 Preparing upload to S3")

        if not os.path.exists(local_path):
            logger.error(f"❌ File not found: {local_path}")
            return

        s3 = boto3.client('s3')
        try:
            logger.info(f"⬆️ Uploading {local_path} to s3://{bucket_name}/{s3_key}")
            s3.upload_file(local_path, bucket_name, s3_key)
            logger.info("✅ Upload successful!")
        except Exception as e:
            logger.error(f"❌ Upload to S3 failed: {e}")

    def handle_message(self, msg):
        chat_id = msg['chat']['id']
        logger.info(f'Incoming message: {msg}')

        if 'text' in msg and msg['text'].strip().lower() == 'hi':
            self.send_text(chat_id, "Hi, how can I help you?")
            return

        if self.is_current_msg_photo(msg):
            try:
                photo_path = self.download_user_photo(msg)
            except Exception:
                return

            caption = msg.get('caption', '').strip().lower().strip(string.punctuation)
            logger.info(f"📸 Caption received: '{caption}'")

            media_group_id = msg.get('media_group_id')
            if media_group_id:
                group = self.media_groups.setdefault(media_group_id, {
                    'chat_id': chat_id,
                    'photos': [],
                    'filter': caption if caption else None,
                    'timer': None
                })
                group['photos'].append(photo_path)
                if caption:
                    group['filter'] = caption
                if group['timer']:
                    group['timer'].cancel()
                timer = threading.Timer(2.0, self._process_media_group, args=(media_group_id,))
                group['timer'] = timer
                timer.start()
                return

            if not caption:
                self.send_text(chat_id, "You need to choose a filter.")
                return

            if caption == 'yolo':
                self.apply_yolo(chat_id, photo_path)
            else:
                self.apply_filter_from_caption(chat_id, photo_path, caption)
            return

        self.send_text(chat_id, "Please send a photo with a caption indicating the filter to apply.")

    def apply_filter_from_caption(self, chat_id, photo_path, caption):
        img = Img(photo_path)
        try:
            if caption == 'blur':
                img.blur()
            elif caption == 'rotate':
                img.rotate()
            elif caption in ('salt and pepper', 'salt_n_pepper'):
                img.salt_n_pepper()
            elif caption == 'contour':
                img.contour()
            elif caption == 'segment':
                img.segment()
            else:
                self.send_text(chat_id, f"Unknown filter '{caption}'.")
                return

            filtered_path = img.save_img()
            logger.info(f"🖼️ Filter applied: {caption} → Saved locally at {filtered_path}")

            # ⛔️ DO NOT upload to S3 for filtered images
            self.send_photo(chat_id, str(filtered_path))

        except Exception:
            logger.exception("Filter application failed")
            self.send_text(chat_id, "Failed to apply the selected filter.")

    def apply_yolo(self, chat_id, photo_path):
        try:
            bucket_name = os.getenv("S3_BUCKET_NAME")
            if not bucket_name:
                self.send_text(chat_id, "S3 bucket not configured. Contact admin.")
                return

            user_id = chat_id
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

            # Upload original image to S3
            original_s3_key = f"original/{user_id}/{timestamp}-{os.path.basename(photo_path)}"
            self.upload_file_to_s3(photo_path, bucket_name, original_s3_key)

            # Send to YOLO service with user_id header
            with open(photo_path, "rb") as f:
                files = {"file": (os.path.basename(photo_path), f, "image/jpeg")}
                headers = {"X-User-ID": str(user_id)}
                response = requests.post(f"{self.yolo_service_url}/predict", files=files, headers=headers)

            response.raise_for_status()
            result = response.json()
            logger.info(f"YOLO raw response: {result}")

            labels = result.get("labels", [])
            prediction_uid = result.get("prediction_uid")
            if not labels:
                self.send_text(chat_id, "No objects detected.")
                return

            # Download predicted image
            predicted_image_url = f"{self.yolo_service_url}/prediction/{prediction_uid}/image"
            predicted_response = requests.get(predicted_image_url, headers={"Accept": "image/jpeg"})
            predicted_response.raise_for_status()

            predicted_img_path = f"{timestamp}_predicted.jpg"
            with open(predicted_img_path, 'wb') as f:
                f.write(predicted_response.content)

            # Upload predicted image to S3
            predicted_s3_key = f"predicted/{user_id}/{predicted_img_path}"
            self.upload_file_to_s3(predicted_img_path, bucket_name, predicted_s3_key)

            # Send results to Telegram user
            result_text = "Detected objects:\n" + "\n".join(labels)
            self.send_text(chat_id, result_text)
            self.send_photo(chat_id, predicted_img_path)

        except Exception as e:
            logger.error(f"YOLO prediction failed: {e}")
            self.send_text(chat_id, "Failed to process image with YOLO.")

import threading
import telebot
from loguru import logger
import os
import time
import boto3
import requests
from telebot.types import InputFile
from polybot.img_proc import Img


class Bot:

    def __init__(self, token, telegram_chat_url):
        self.telegram_bot_client = telebot.TeleBot(token)
        self.telegram_bot_client.remove_webhook()
        time.sleep(0.5)
        self.telegram_bot_client.set_webhook(url=f'{telegram_chat_url}/{token}/', timeout=60)
        logger.info(f'Telegram Bot information\n\n{self.telegram_bot_client.get_me()}')

        self.bucket_name = os.getenv('S3_BUCKET_NAME') or 'maisa-polybot-images'

        if os.getenv("SKIP_S3") == "1":
            self.s3 = None
            logger.warning("🧪 SKIP_S3 is set — skipping S3 setup.")
            return

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

            return file_info.file_path
        except OSError as e:
            logger.error(f"File saving error: {e}")
            self.send_text(msg['chat']['id'], "Something went wrong, try again please.")
            raise

    def send_photo(self, chat_id, img_path):
        if not os.path.exists(img_path):
            raise RuntimeError("Image path doesn't exist")

        self.telegram_bot_client.send_photo(chat_id, InputFile(img_path))

    def upload_to_s3(self, local_path, s3_key):
        if self.s3 is None:
            logger.warning("🧪 Skipping S3 upload due to SKIP_S3 mode.")
            return

        if not os.path.exists(local_path):
            logger.error(f"❌ Local file not found: {local_path}")
            return
        try:
            self.s3.upload_file(local_path, self.bucket_name, s3_key)
            logger.info(f"✅ Uploaded to S3: {s3_key}")
        except Exception as e:
            logger.exception(f"❌ S3 upload failed: {e}")

    def handle_message(self, msg):
        logger.info(f'Incoming message: {msg}')
        text = msg.get("text", "<no text>")
        self.send_text(msg["chat"]["id"], f"Your original message: {text}")


class QuoteBot(Bot):
    def handle_message(self, msg):
        logger.info(f'Incoming message: {msg}')
        text = msg.get("text", "")
        if text != "Please don't quote me":
            self.send_text_with_quote(msg['chat']['id'], text, quoted_msg_id=msg["message_id"])


class ImageProcessingBot(Bot):
    def __init__(self, token, telegram_chat_url, yolo_service_url=None):
        super().__init__(token, telegram_chat_url)
        self.media_groups = {}
        self.yolo_service_url = yolo_service_url

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

            media_group_id = msg.get('media_group_id')
            caption = msg.get('caption', '').strip().lower()

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

            self.apply_filter_from_caption(chat_id, photo_path, caption)
            return

        self.send_text(chat_id, "Please send a photo with a caption indicating the filter to apply.")

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
            self.send_text(chat_id, "Concat failed. Make sure both images are compatible.")

    def apply_filter_from_caption(self, chat_id, photo_path, caption):
        try:
            if caption == 'blur':
                img = Img(photo_path)
                img.blur()
                filtered_path = img.save_img()
            elif caption == 'rotate':
                img = Img(photo_path)
                img.rotate()
                filtered_path = img.save_img()
            elif caption in ('salt and pepper', 'salt_n_pepper'):
                img = Img(photo_path)
                img.salt_n_pepper()
                filtered_path = img.save_img()
            elif caption == 'contour':
                img = Img(photo_path)
                img.contour()
                filtered_path = img.save_img()
            elif caption == 'segment':
                img = Img(photo_path)
                img.segment()
                filtered_path = img.save_img()
            elif caption == 'yolo':
                self.apply_yolo_filter(chat_id, photo_path)
                return
            else:
                self.send_text(chat_id, f"Unknown filter '{caption}'. Available filters: blur, rotate, salt and pepper, contour, segment, yolo.")
                return

            self.upload_to_s3(filtered_path, f"filtered/{chat_id}/{os.path.basename(filtered_path)}")
            self.send_photo(chat_id, str(filtered_path))
        except Exception as e:
            logger.error(f"Error applying filter: {e}")
            self.send_text(chat_id, "An error occurred while applying the filter.")

    def apply_yolo_filter(self, chat_id, photo_path):
        if not self.yolo_service_url:
            self.send_text(chat_id, "YOLO service is not configured.")
            return

        try:
            with open(photo_path, 'rb') as f:
                files = {'file': f}
                response = requests.post(f"{self.yolo_service_url}/predict", files=files, timeout=30)

            if response.status_code != 200:
                self.send_text(chat_id, f"YOLO service error: {response.status_code}")
                return

            result = response.json()
            prediction_path = result.get('prediction_path')
            labels = result.get('labels', [])

            if prediction_path:
                self.send_text(chat_id, f"Detected: {', '.join(labels) if labels else 'No objects'}")
                self.send_photo(chat_id, prediction_path)
            else:
                self.send_text(chat_id, "YOLO prediction succeeded, but no result image returned.")
        except Exception as e:
            logger.error(f"YOLO error: {e}")
            self.send_text(chat_id, "YOLO filter failed. Please try again.")

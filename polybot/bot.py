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
            raise RuntimeError(f'Message content of type \'photo\' expected')

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

    def handle_message(self, msg):
        logger.info(f'Incoming message: {msg}')
        self.send_text(msg['chat']['id'], f'Your original message: {msg["text"]}')


class QuoteBot(Bot):
    def handle_message(self, msg):
        logger.info(f'Incoming message: {msg}')
        if msg["text"] != 'Please don\'t quote me':
            self.send_text_with_quote(msg['chat']['id'], msg["text"], quoted_msg_id=msg["message_id"])


class ImageProcessingBot(Bot):
    def __init__(self, token, telegram_chat_url, yolo_service_url='http://localhost:8080'):
        super().__init__(token, telegram_chat_url)
        self.media_groups = {}
        self.yolo_service_url = yolo_service_url

    def upload_file_to_s3(self, local_path, bucket_name, s3_key):
        """
        Uploads a local file to the specified S3 bucket with the given key.

        Args:
            local_path (str): Path to the local file to upload.
            bucket_name (str): Name of the target S3 bucket.
            s3_key (str): S3 object key (i.e., the file path in the bucket).
        """
        logger.info("📦 Preparing upload to S3")

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

                # Upload to S3 after saving
                bucket_name = os.getenv("S3_BUCKET_NAME")
                if bucket_name:
                    user_id = msg['from']['id']
                    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                    s3_key = f"original/{user_id}/{timestamp}-{os.path.basename(photo_path)}"
                    self.upload_file_to_s3(photo_path, bucket_name, s3_key)
                    logger.info(f"Uploaded original image to S3 bucket {bucket_name} at {s3_key}")
                else:
                    logger.warning("S3_BUCKET_NAME not set. Skipping S3 upload.")

            except Exception:
                return

            caption = msg.get('caption', '').strip().lower().strip(string.punctuation)
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

            raw_caption = msg.get('caption', '')
            caption = raw_caption.strip().lower().strip(string.punctuation)
            logger.info(f"📸 Caption received: '{caption}'")

            # Decide whether to run YOLO or apply a regular filter
            if caption == 'yolo':
                self.apply_yolo(chat_id, photo_path)
            elif caption:
                self.apply_filter_from_caption(chat_id, photo_path, caption)
            else:
                self.send_text(chat_id, "You need to choose a filter.")

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
            self.send_photo(chat_id, str(result_path))
        except Exception as e:
            logger.error(f"Concat error: {e}")
            self.send_text(chat_id, "Concat failed. Make sure both images are compatible.")

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
            self.send_photo(chat_id, str(filtered_path))
        except Exception:
            logger.exception("YOLO prediction failed:")

    def apply_yolo(self, chat_id, photo_path):
        try:
            bucket_name = os.getenv("S3_BUCKET_NAME")
            if not bucket_name:
                self.send_text(chat_id, "S3 bucket not configured. Contact admin.")
                return

            # Step 1: Upload original image to S3
            user_id = chat_id
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            s3_key = f"original/{user_id}/{timestamp}-{os.path.basename(photo_path)}"
            self.upload_file_to_s3(photo_path, bucket_name, s3_key)

            # Step 2: Call YOLO service with image name
            response = requests.post(
                f"{self.yolo_service_url}/predict",
                json={"image_name": s3_key}
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"YOLO raw response: {result}")

            labels = result.get("labels", [])
            prediction_uid = result.get("prediction_uid")

            if not labels:
                self.send_text(chat_id, "No objects detected.")
                return

            # Step 3: Download predicted image from YOLO service
            predicted_image_url = f"{self.yolo_service_url}/prediction/{prediction_uid}/image"
            predicted_response = requests.get(predicted_image_url)
            predicted_response.raise_for_status()

            predicted_img_path = f"predicted_{os.path.basename(photo_path)}"
            with open(predicted_img_path, 'wb') as f:
                f.write(predicted_response.content)

            # Step 4: Upload predicted image to S3
            pred_s3_key = f"predicted/{user_id}/{timestamp}-{os.path.basename(predicted_img_path)}"
            self.upload_file_to_s3(predicted_img_path, bucket_name, pred_s3_key)

            # Step 5: Send results to user
            result_text = "Detected objects:\n" + "\n".join(labels)
            self.send_text(chat_id, result_text)
            self.send_photo(chat_id, predicted_img_path)

        except Exception as e:
            logger.error(f"YOLO prediction failed: {e}")
            self.send_text(chat_id, "Failed to process image with YOLO.")




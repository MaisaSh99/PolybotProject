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
        logger.info(f"🪣 Using S3 bucket: {self.bucket_name}")
        self.s3 = boto3.client('s3', region_name='us-east-2')
        self.s3.upload_file('/tmp/test.jpg', 'maisa-dev-bucket', 'beatles.jpeg')

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

            logger.info(f"✅ Photo saved locally: {file_info.file_path}")
            return file_info.file_path
        except OSError as e:
            logger.error(f"❌ File saving error: {e}")
            self.send_text(msg['chat']['id'], "Something went wrong, try again please.")
            raise

    def send_photo(self, chat_id, img_path):
        if not os.path.exists(img_path):
            raise RuntimeError("Image path doesn't exist")

        self.telegram_bot_client.send_photo(chat_id, InputFile(img_path))

    def handle_message(self, msg):
        logger.info(f'Incoming message: {msg}')
        self.send_text(msg['chat']['id'], f'Your original message: {msg["text"]}')

    def upload_to_s3(self, local_path, s3_path):
        logger.info(f"📤 Uploading {local_path} to s3://{self.bucket_name}/{s3_path}")

        try:
            logger.info("🔍 Checking if file exists and is not empty...")
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


class ImageProcessingBot(Bot):
    def __init__(self, token, telegram_chat_url, yolo_service_url='http://localhost:8080'):
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

            caption = msg.get('caption', '').strip().lower()
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
                self.apply_yolo(msg, photo_path)
            else:
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
        except Exception as e:
            logger.error(f"Error applying filter: {e}")
            self.send_text(chat_id, "An error occurred while applying the filter.")

    def apply_yolo(self, msg, photo_path):
        try:
            chat_id = msg['chat']['id']
            from_id = msg.get('from', {}).get('id')
            telegram_user_id = str(from_id if from_id is not None else chat_id)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

            logger.info(f"🖼️ Using downloaded photo at: {photo_path}")

            # Upload original image to S3
            original_s3_key = f"original/{telegram_user_id}/{timestamp}.jpg"
            logger.info(f"📂 Uploading original image to s3://{self.bucket_name}/{original_s3_key}")
            self.upload_to_s3(photo_path, original_s3_key)

            logger.info(f"[Polybot] Original image uploaded. Proceeding to YOLO prediction.")
            logger.info(f"📡 Sending prediction request to {self.yolo_service_url}/predict")

            # Open the file and send it as a multipart form
            with open(photo_path, 'rb') as f:
                files = {'file': (os.path.basename(photo_path), f, 'image/jpeg')}
                response = requests.post(
                    f"{self.yolo_service_url}/predict",
                    files=files
                )

            response.raise_for_status()
            result = response.json()
            logger.info(f"YOLO raw response: {result}")

            labels = result.get("labels", [])
            if not labels:
                self.send_text(chat_id, "No objects detected.")
                return

            result_text = "Detected objects:\n" + "\n".join(labels)
            self.send_text(chat_id, result_text)

            # Get and send the predicted image
            prediction_uid = result.get("prediction_uid")
            if prediction_uid:
                predicted_image_url = f"{self.yolo_service_url}/prediction/{prediction_uid}/image"
                predicted_response = requests.get(predicted_image_url)
                if predicted_response.status_code == 200:
                    # Save the predicted image temporarily
                    predicted_path = f"/tmp/predicted_{timestamp}.jpg"
                    with open(predicted_path, 'wb') as f:
                        f.write(predicted_response.content)
                    
                    # Upload predicted image to S3
                    predicted_s3_key = f"predicted/{telegram_user_id}/{timestamp}_predicted.jpg"
                    logger.info(f"📂 Uploading predicted image to s3://{self.bucket_name}/{predicted_s3_key}")
                    self.upload_to_s3(predicted_path, predicted_s3_key)
                    
                    # Send the predicted image back to the user
                    self.send_photo(chat_id, predicted_path)
                    
                    # Clean up temporary files
                    os.remove(predicted_path)
                    os.remove(photo_path)  # Also clean up the original downloaded photo

        except Exception as e:
            logger.error(f"YOLO prediction failed: {e}")
            self.send_text(chat_id, "Failed to process image with YOLO.")


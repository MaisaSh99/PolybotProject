#!/bin/bash

echo -e "\n\n🔬 Testing concat()\n"
python -m polybot.test.test_concat

echo -e "\n\n🔁 Testing rotate()\n"
python -m polybot.test.test_rotate

echo -e "\n\n🧂 Testing salt_n_pepper()\n"
python -m polybot.test.test_salt_n_pepper

echo -e "\n\n📐 Testing segment()\n"
python -m polybot.test.test_segment

echo -e "\n\n🤖 Testing Telegram bot logic\n"
python -m polybot.test.test_telegram_bot

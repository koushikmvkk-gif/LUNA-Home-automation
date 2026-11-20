#!/usr/bin/env python3
"""Check your Telegram bot token / chat id from the Pi:  ./venv/bin/python tools/test_telegram.py"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
import config as cfg
d = json.load(open(os.path.join(cfg.DATA_DIR, "telegram.json")))
tok, chat = d.get("token") or d.get("bot_token"), d.get("chat_id")
me = requests.get("https://api.telegram.org/bot%s/getMe" % tok, timeout=10).json()
print("bot  :", me.get("result", {}).get("username"), "ok" if me.get("ok") else me)
r = requests.post("https://api.telegram.org/bot%s/sendMessage" % tok, data={"chat_id": chat, "text": "Luna test message \u2705"}, timeout=10)
print("send :", r.status_code, r.text[:120])

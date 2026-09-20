#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚀 V2Ray Subscriptions Runner
جمع‌آوری، تست و ارسال کانفیگ‌های V2Ray به تلگرام
"""

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import json
import os
import re
import socket
import ssl
import time
from urllib.parse import parse_qs, quote, urlparse
import requests

# ---------------------------------------------------------
# دریافت اطلاعات محرمانه از GitHub Secrets
# ---------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()
SOURCES_RAW = os.environ.get("SOURCES_JSON", "{}").strip()

try:
    SOURCES = json.loads(SOURCES_RAW)
except Exception as e:
    print(f"❌ خطا در خواندن SOURCES_JSON: {e}")
    SOURCES = {}

SAFE_TLS_PORTS = {443, 8443, 2053, 2083, 2087, 2096, 2052, 8080, 8880}
TIMEOUT = 1.8
MAX_WORKERS = 80


def get_flag(country_code):
    if country_code and len(country_code) == 2:
        return "".join(chr(127397 + ord(x.upper())) for x in country_code)
    return "🌐"


def fetch_geo_batch(ip_list):
    geo = {}
    if not ip_list:
        return geo
    for i in range(0, len(ip_list), 100):
        batch = ip_list[i:i + 100]
        try:
            r = requests.post(
                "http://ip-api.com/batch?fields=query,status,country,city,countryCode",
                json=batch,
                timeout=10
            )
            if r.status_code == 200:
                for item in r.json():
                    if item.get("status") == "success":
                        geo[item["query"]] = {
                            "country": item.get("country", "Unknown"),
                            "city": item.get("city", "Unknown"),
                            "flag": get_flag(item.get("countryCode", ""))
                        }
        except Exception as e:
            print(f"⚠️ خطا در geo lookup: {e}")
    return geo


def validate_environment():
    """بررسی صحت متغیرهای محیطی"""
    if not BOT_TOKEN:
        print("⚠️ BOT_TOKEN تنظیم نشده است.")
        return False
    if not CHAT_ID:
        print("⚠️ CHAT_ID تنظیم نشده است.")
        return False
    return True


def send_to_telegram(text, file_path=None):
    """ارسال پیام یا فایل به تلگرام"""
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ BOT_TOKEN یا CHAT_ID تنظیم نشده‌اند.")
        return False

    try:
        if file_path and os.path.exists(file_path):
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
            with open(file_path, 'rb') as f:
                files = {'document': f}
                data = {'chat_id': CHAT_ID, 'caption': text[:1024]}
                r = requests.post(url, files=files, data=data, timeout=30)
        else:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            data = {'chat_id': CHAT_ID, 'text': text[:4096], 'parse_mode': 'HTML'}
            r = requests.post(url, json=data, timeout=30)

        if r.status_code == 200:
            print("✅ ارسال موفق به تلگرام")
            return True
        else:
            print(f"❌ خطا در ارسال: {r.status_code} - {r.text}")
            return False
    except Exception as e:
        print(f"❌ خطا: {e}")
        return False


def main():
    if not validate_environment():
        return

    print("🚀 شروع اجرا...")
    # ... بقیه منطق شما
    print("✅ پایان")


if __name__ == "__main__":
    main(

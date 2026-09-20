
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚀 Telegram Proxy Collector v2.4
- دکمه‌های شیشه‌ای زیبا برای ۳ پروکسی برتر
- بدون سنجاق خودکار پیام
"""

import asyncio
import os
import re
import sys
import json
import logging
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from pathlib import Path

import aiohttp

# ==================== تنظیم Logging ====================
def setup_logging():
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler('proxy_collector.log', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ==================== تنظیمات ====================
OUTPUT_FILE = "TELEGRAM_PROXY_SUB_TXT"
CHANNEL_LINK = "https://t.me/Goodbaye_filtering"

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

def load_sources_from_env() -> List[str]:
    raw_json = os.environ.get("SOURCES_JSON", "").strip()
    if not raw_json:
        logger.error("❌ متغیر SOURCES_JSON یافت نشد!")
        return []
    try:
        data = json.loads(raw_json)
        sources = data.get("by8", [])
        logger.info(f"🔑 تعداد {len(sources)} منبع پروکسی از SOURCES_JSON استخراج شد.")
        return sources
    except Exception as e:
        logger.error(f"❌ خطا در خواندن SOURCES_JSON: {e}")
        return []

SOURCES = load_sources_from_env()

FETCH_TIMEOUT = 15.0
TCP_TIMEOUT = 5.0
MAX_CONCURRENT_TESTS = 40
MAX_RETRIES = 3
RETRY_DELAY = 2.0

PROXY_RE = re.compile(r"(?:https?://t\.me|tg://)/?(?:proxy)?\?[^\s'\"<>]+")


# ==================== Validation ====================
def validate_environment():
    logger.info("🔍 بررسی متغیرهای محیطی...")
    if not BOT_TOKEN:
        logger.warning("⚠️ BOT_TOKEN تنظیم نشده است.")
        return False
    if not CHAT_ID:
        logger.warning("⚠️ CHAT_ID تنظیم نشده است.")
        return False
    logger.info("✅ متغیرهای محیطی بررسی شدند.")
    return True


# ==================== Data Classes ====================
@dataclass
class ProxyLink:
    server: str
    port: int
    secret: str
    raw: str
    latency: float = 999.0

    def __hash__(self):
        return hash((self.server, self.port, self.secret))

    def __eq__(self, other):
        if not isinstance(other, ProxyLink):
            return False
        return (self.server, self.port, self.secret) == (other.server, other.port, other.secret)


# ==================== Parsing ====================
def parse_proxy_line(line: str) -> Optional[ProxyLink]:
    line = line.strip()
    if not line:
        return None
    try:
        m = PROXY_RE.search(line)
        if not m:
            return None
        url = m.group(0)
        normalized = url if url.startswith("http") else "https://t.me/proxy" + url[url.index("?"):]
        parsed = urlparse(normalized)
        qs = parse_qs(parsed.query)
        server = (qs.get("server", [""])[0] or "").strip().rstrip(".").lower()
        port_raw = (qs.get("port", [""])[0] or "").strip()
        secret = (qs.get("secret", [""])[0] or "").strip()
        if not server or not port_raw.isdigit() or not secret:
            return None
        port = int(port_raw)
        if not (0 < port < 65536):
            return None
        clean_url = f"https://t.me/proxy?server={server}&port={port}&secret={secret}"
        return ProxyLink(server=server, port=port, secret=secret, raw=clean_url)
    except Exception as e:
        logger.debug(f"خطا در تجزیه: {e}")
        return None


# ==================== Fetching ====================
async def fetch_source(session: aiohttp.ClientSession, url: str, retries: int = MAX_RETRIES) -> List[str]:
    for attempt in range(retries):
        try:
            logger.info(f"📥 دریافت منبع (تلاش {attempt + 1}/{retries})...")
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT),
                ssl=False,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            ) as r:
                if r.status != 200:
                    if attempt < retries - 1:
                        await asyncio.sleep(RETRY_DELAY)
                    continue
                text = await r.text(errors="ignore")
                return text.splitlines()
        except asyncio.TimeoutError:
            if attempt < retries - 1:
                await asyncio.sleep(RETRY_DELAY)
        except Exception as e:
            if attempt < retries - 1:
                await asyncio.sleep(RETRY_DELAY)
    return []


async def collect_all() -> List[ProxyLink]:
    logger.info("=" * 60)
    logger.info("🚀 شروع جمع‌آوری پروکسی‌ها")
    logger.info("=" * 60)
    if not SOURCES:
        logger.error("❌ هیچ منبعی وجود ندارد!")
        return []
    connector = aiohttp.TCPConnector(limit_per_host=5, limit=100, ttl_dns_cache=300, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        all_lines = await asyncio.gather(
            *[fetch_source(session, u) for u in SOURCES],
            return_exceptions=True
        )
    seen: Set[Tuple[str, int, str]] = set()
    proxies: List[ProxyLink] = []
    for i, lines in enumerate(all_lines):
        if isinstance(lines, Exception):
            continue
        for line in lines:
            p = parse_proxy_line(line)
            if not p:
                continue
            key = (p.server, p.port, p.secret)
            if key in seen:
                continue
            seen.add(key)
            proxies.append(p)
    logger.info(f"✅ {len(proxies)} پروکسی یکتا جمع‌آوری شد")
    return proxies


# ==================== Testing ====================
async def measure_latency(p: ProxyLink, sem: asyncio.Semaphore) -> Optional[ProxyLink]:
    async with sem:
        start_time = asyncio.get_event_loop().time()
        writer = None
        try:
            fut = asyncio.open_connection(p.server, p.port)
            _, writer = await asyncio.wait_for(fut, timeout=TCP_TIMEOUT)
            end_time = asyncio.get_event_loop().time()
            p.latency = round((end_time - start_time) * 1000, 2)
            return p
        except Exception:
            return None
        finally:
            if writer is not None:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass


async def filter_and_sort_alive(proxies: List[ProxyLink]) -> List[ProxyLink]:
    logger.info(f"🧪 تست {len(proxies)} پروکسی...")
    sem = asyncio.Semaphore(MAX_CONCURRENT_TESTS)
    results = await asyncio.gather(*[measure_latency(p, sem) for p in proxies])
    alive_proxies = [p for p in results if p is not None]
    alive_proxies.sort(key=lambda x: x.latency)
    logger.info(f"✅ {len(alive_proxies)} پروکسی زنده")
    return alive_proxies


# ==================== File Operations ====================
async def save_proxies_to_file(file_path: str, proxies: List[ProxyLink]) -> bool:
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(p.raw for p in proxies))
        logger.info(f"💾 {len(proxies)} پروکسی ذخیره شد")
        return True
    except Exception as e:
        logger.error(f"❌ خطا: {e}")
        return False


# ==================== Telegram Sending ====================
def get_speed_emoji(latency: float) -> str:
    """انتخاب ایموجی بر اساس سرعت"""
    if latency < 100:
        return "🚀"
    elif latency < 200:
        return "⚡"
    elif latency < 400:
        return "🔥"
    else:
        return "🐢"


def get_speed_label(latency: float) -> str:
    """برچسب سرعت"""
    if latency < 100:
        return "فوق‌سریع"
    elif latency < 200:
        return "سریع"
    elif latency < 400:
        return "خوب"
    else:
        return "معمولی"


async def send_to_telegram(file_path: str, proxies: List[ProxyLink]) -> None:
    """ارسال فایل + پیام ۳ پروکسی برتر با دکمه‌های شیشه‌ای (بدون سنجاق)"""
    if not BOT_TOKEN or not CHAT_ID:
        logger.warning("⚠️ BOT_TOKEN یا CHAT_ID تنظیم نشده است.")
        return
    if not Path(file_path).exists():
        logger.error(f"❌ فایل «{file_path}» وجود ندارد.")
        return

    count = len(proxies)
    logger.info(f"📤 ارسال {count} پروکسی به تلگرام...")
    
    # ==================== کپشن فایل ====================
    caption = (
        f"📦 <b>{count}</b> پروکسی زنده\n"
        f"⏱ {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"✨ {CHANNEL_LINK}"
    )

    url_doc = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    url_msg = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    try:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            
            # ==================== ۱. ارسال فایل ====================
            with open(file_path, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("chat_id", CHAT_ID)
                data.add_field("caption", caption)
                data.add_field("parse_mode", "HTML")
                data.add_field(
                    "document", f,
                    filename=os.path.basename(file_path),
                    content_type="text/plain",
                )
                try:
                    async with session.post(
                        url_doc,
                        data=data,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as r:
                        res = await r.json()
                        if res.get("ok"):
                            logger.info("✅ فایل ارسال شد")
                        else:
                            logger.error(f"❌ خطا: {res.get('description')}")
                except Exception as e:
                    logger.error(f"❌ خطا در ارسال فایل: {e}")

            # ==================== ۲. پیام ۳ پروکسی برتر با دکمه‌های زیبا ====================
            if proxies:
                top_proxies = proxies[:3]
                
                # ساخت متن پیام
                text_lines = [
                    "🏆 <b>۳ پروکسی فوق‌سریع برتر</b>",
                    "━━━━━━━━━━━━━━━━━━━━",
                ]
                
                medals = ["🥇", "🥈", "🥉"]
                for i, p in enumerate(top_proxies, 1):
                    speed_emoji = get_speed_emoji(p.latency)
                    speed_label = get_speed_label(p.latency)
                    text_lines.append(
                        f"\n{medals[i-1]} <b>پروکسی {i}</b>\n"
                        f"{speed_emoji} سرعت: <b>{int(p.latency)}ms</b> ({speed_label})\n"
                        f"🌐 سرور: <code>{p.server}</code>\n"
                        f"🔌 پورت: <code>{p.port}</code>"
                    )
                
                text_lines.append("\n━━━━━━━━━━━━━━━━━━━━")
                text_lines.append(f"💎 <i>از بین {count} پروکسی تست‌شده</i>")
                text_lines.append(f"🔄 <i>بروزرسانی خودکار هر ۴ ساعت</i>")
                
                # ساخت دکمه‌های شیشه‌ای زیبا
                inline_keyboard = []
                for i, p in enumerate(top_proxies, 1):
                    speed_emoji = get_speed_emoji(p.latency)
                    inline_keyboard.append([
                        {
                            "text": f"{medals[i-1]} {speed_emoji} اتصال به پروکسی {i} ({int(p.latency)}ms)",
                            "url": p.raw
                        }
                    ])
                
                # دکمه کانال
                inline_keyboard.append([
                    {"text": "📢 کانال ما", "url": CHANNEL_LINK}
                ])

                payload = {
                    "chat_id": CHAT_ID,
                    "text": "\n".join(text_lines),
                    "parse_mode": "HTML",
                    "reply_markup": {"inline_keyboard": inline_keyboard}
                    # ⚠️ هیچ disable_notification یا pin — یعنی سنجاق نمیشه
                }

                try:
                    async with session.post(
                        url_msg,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as r:
                        res = await r.json()
                        if res.get("ok"):
                            logger.info("✅ پیام با دکمه‌های شیشه‌ای ارسال شد")
                        else:
                            logger.error(f"❌ خطا: {res.get('description')}")
                except Exception as e:
                    logger.error(f"❌ خطا در ارسال پیام: {e}")

    except Exception as e:
        logger.error(f"❌ خطا در ارتباط با تلگرام: {e}")


# ==================== Main ====================
async def main() -> None:
    logger.info("\n" + "=" * 60)
    logger.info("🚀 Telegram Proxy Collector v2.4 - شروع")
    logger.info("=" * 60 + "\n")
    has_telegram = validate_environment()
    try:
        all_proxies = await collect_all()
        if not all_proxies:
            logger.error("❌ هیچ پروکسی جمع‌آوری نشد!")
            return
        alive = await filter_and_sort_alive(all_proxies)
        if not alive:
            logger.error("❌ هیچ پروکسی سالم پیدا نشد!")
            return
        if not await save_proxies_to_file(OUTPUT_FILE, alive):
            return
        if has_telegram:
            await send_to_telegram(OUTPUT_FILE, alive)
        logger.info("\n" + "=" * 60)
        logger.info("✅ فرآیند با موفقیت تمام شد")
        logger.info("=" * 60 + "\n")
    except Exception as e:
        logger.error(f"❌ خطای غیرمنتظره: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n⚠️ توقف (Ctrl+C)")
    except Exception as e:
        logger.error(f"❌ خطای بحرانی: {e}", exc_info=True)
        sys.exit(1)

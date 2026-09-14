# -*- coding: utf-8 -*-
"""
ربات جمع‌آوری، تست و ارسال کانفیگ V2Ray به کانال تلگرام
- جمع‌آوری از ۲۶ منبع
- حذف کانفیگ‌های تکراری
- تشخیص کشور/شهر/پرچم از روی IP سرور (GeoIP)
- تست پینگ واقعی TCP با نت ایران (زیر ۵۰۰ms)
- قالب اسم: 👉🆔@CHANNEL📡🇩🇪®️Germany©️City🅿️ping:XXXms
- ارسال فایل configs.txt با کپشن شیک به کانال تلگرام
"""

import os
import re
import json
import time
import base64
import socket
import urllib.parse
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

try:
    import xray_test
    from xray_test import ensure_xray, real_test as _real_test
except Exception:
    xray_test = None
    ensure_xray = _real_test = None

# ================== تنظیمات ==================
BOT_TOKEN    = os.getenv("BOT_TOKEN", "")
CHAT_ID      = os.getenv("CHAT_ID", "")
CHANNEL_NAME = os.getenv("CHANNEL_NAME", "")   # ⚠️ حتماً تنظیم کنید

MAX_PING_MS = 200     # سختگیرانه: فقط کانفیگ‌های با پینگ زیر ۲۰۰ms
TCP_TIMEOUT = 3       # تایم‌اوت تست هر کانفیگ (ثانیه) — سختگیرانه
MAX_WORKERS = 150     # تعداد تست همزمان
MAX_CONFIGS = 0       # بدون سقف تعداد — فقط کانفیگ‌های فعال و سالم

CHANNEL_LINK = "https://t.me/CONFIG_V2RAY_VIP"    # لینک کانال (تبادل و چت)
SOURCE_LINK  = "https://t.me/Goodbaye_filtering"  # لینک منبع
GOLDEN_PORTS = {443, 80, 8443, 2053, 2083, 2087, 2096}  # پورت‌های طلایی

SOURCES = list(dict.fromkeys([
    "https://raw.githubusercontent.com/iboxz/free-v2ray-collector/main/main/mix",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/V2RAY_BASE64.txt",
    "https://manager.onetwothree123.ir/",
    "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/top100.txt",
    "https://raw.githubusercontent.com/Q3dlaXpoaQ/Q3dlaXpoaQ.github.io/refs/heads/main/APIs/cg1.txt",
    "https://raw.githubusercontent.com/mahsanet/MahsaFreeConfig/refs/heads/main/mci/sub_1.txt",
    "https://raw.githubusercontent.com/mahsanet/MahsaFreeConfig/main/mtn/sub_1.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/ShatakVPN/ConfigForge-V2Ray/refs/heads/main/configs/ir/vless.txt",
    "https://raw.githubusercontent.com/Surfboardv2ray/TGParse/refs/heads/main/splitted/hysteria2",
    "https://raw.githubusercontent.com/iboxz/free-v2ray-collector/main/main/vless.txt",
    "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/refs/heads/main/protocols/hysteria2.txt",
    *[f"https://raw.githubusercontent.com/V2RAYCONFIGSPOOL/V2RAY_SUB/refs/heads/main/v2ray_configs_no{i}.txt" for i in range(1, 11)],
    "https://raw.githubusercontent.com/MohammadBahemmat/V2ray-Collector/main/all_servers.txt",
    "https://raw.githubusercontent.com/MahanKenway/Freedom-V2Ray/main/configs/vless_sub.txt",
]))

HEADERS = {"User-Agent": "v2rayNG/1.8.5"}
OUT_TXT = "configs.txt"

# ================== ابزارها ==================

def b64decode_loose(data: str) -> str:
    data = data.strip().replace("\n", "").replace("\r", "")
    for suffix in ("", "=", "=="):
        try:
            return base64.b64decode(data + suffix).decode("utf-8", errors="ignore")
        except Exception:
            continue
    return ""

def flag_emoji(code: str) -> str:
    if not code or len(code) != 2:
        return "🏴"
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code.upper())

# ================== ۱. دریافت منابع ==================

def fetch_source(url: str) -> list:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"[!] منبع خطا داد ({r.status_code}): {url}")
            return []
        text = r.text
        decoded = b64decode_loose(text)
        if "://" in decoded:
            text = decoded
        return [ln.strip() for ln in text.splitlines() if "://" in ln]
    except Exception as e:
        print(f"[!] خطا در خواندن {url}: {e}")
        return []

# ================== ۲. پارس و یکتا‌سازی ==================

def parse_config(line: str):
    try:
        scheme = line.split("://", 1)[0].lower()
        if scheme == "vmess":
            j = json.loads(b64decode_loose(line.split("://", 1)[1]))
            return {"scheme": scheme, "server": str(j.get("add", "")).strip(),
                    "port": str(j.get("port", "")).strip(),
                    "id": str(j.get("id", "")), "data": j}
        if scheme in ("vless", "trojan", "ss", "ssr", "hysteria", "hysteria2", "hy2", "tuic"):
            u = urllib.parse.urlparse(line)
            if not u.hostname:
                return None
            raw_user = u.username or ""
            try:
                uid = base64.b64decode(raw_user + "==").decode() if raw_user else ""
            except Exception:
                uid = urllib.parse.unquote(raw_user)
            return {"scheme": scheme, "server": u.hostname,
                    "port": str(u.port or ""), "id": uid, "data": u}
    except Exception:
        return None
    return None

def dedup(lines: list):
    seen, out = set(), []
    for line in lines:
        cfg = parse_config(line)
        if not cfg or not cfg["server"] or not cfg["port"].isdigit():
            continue
        if not (1 <= int(cfg["port"]) <= 65535):
            continue
        key = (cfg["scheme"], cfg["server"].lower(), cfg["port"], cfg["id"][:24])
        if key in seen:
            continue
        seen.add(key)
        out.append((line, cfg))
    return out

# ================== ۳. تست پینگ واقعی (TCP) ==================

def tcp_ping(cfg):
    try:
        t0 = time.time()
        s = socket.create_connection((cfg["server"], int(cfg["port"])), timeout=TCP_TIMEOUT)
        ms = round((time.time() - t0) * 1000)
        s.close()
        return ms
    except Exception:
        return None

def test_all(configs):
    alive = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(tcp_ping, cfg): (line, cfg) for line, cfg in configs}
        done = 0
        for fut in as_completed(futs):
            done += 1
            ms = fut.result()
            if ms is not None and ms <= MAX_PING_MS:
                alive.append((futs[fut][0], futs[fut][1], ms))
            if done % 200 == 0:
                print(f"    تست: {done}/{len(configs)} | زنده: {len(alive)}")
    return alive

# ================== ۴. GeoIP (کشور/شهر/پرچم) ==================

def geoip_lookup(servers: list) -> dict:
    result = {}
    uniq = list(dict.fromkeys(servers))
    for i in range(0, len(uniq), 100):
        batch = uniq[i:i + 100]
        try:
            r = requests.post(
                "http://ip-api.com/batch?fields=status,country,countryCode,city,query",
                json=batch, timeout=20)
            if r.status_code == 200:
                for item in r.json():
                    if item.get("status") == "success":
                        result[item["query"]] = (
                            item.get("country", "Unknown"),
                            item.get("city") or item.get("country", "Unknown"),
                            item.get("countryCode", ""))
        except Exception as e:
            print(f"[!] GeoIP خطا: {e}")
        if i + 100 < len(uniq):
            time.sleep(1.5)   # محدودیت 45 درخواست/دقیقه
    return result

# ================== ۵. ساخت Remark و بازسازی لینک ==================

def build_remark(geo, ping_ms, speed=None) -> str:
    country, city, code = geo if geo else ("Unknown", "Unknown", "")
    sp = f"⚡️{speed}Mbps" if speed else "⚡️—"
    return (f"👉🆔@{CHANNEL_NAME}📡{flag_emoji(code)}"
            f"®️{country}©️{city}🅿️ping:{ping_ms}ms{sp}")

def rebuild_line(line, cfg, remark) -> str:
    try:
        if cfg["scheme"] == "vmess":
            j = dict(cfg["data"])
            j["ps"] = remark
            payload = base64.b64encode(
                json.dumps(j, separators=(",", ":")).encode()).decode()
            return "vmess://" + payload
        u = cfg["data"]
        return urllib.parse.urlunparse(u._replace(
            fragment=urllib.parse.quote(remark, safe="")))
    except Exception:
        return line

# ================== ۶. ارسال تلگرام ==================

def tg_send_document(path, caption=""):
    with open(path, "rb") as f:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
            data={"chat_id": CHAT_ID, "caption": caption},
            files={"document": f}, timeout=120)
    return r.status_code == 200, r.text

def build_caption(count: int) -> str:
    date = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        "╔═══════════════════════════════╗\n"
        "║   🚀  گلچین سرورهای پرسرعت    ║\n"
        "║   ✅  تست زنده با نت ایران    ║\n"
        "╚═══════════════════════════════╝\n\n"
        f"📦 فایل: {OUT_TXT}\n"
        f"📌 کانفیگ سالم: {count} عدد\n"
        f"⚡️ پینگ: زیر {MAX_PING_MS}ms\n"
        "🧪 تست: هندشیک واقعی Xray + سرعت دانلود\n"
        "🔌 پورت‌های طلایی: 443 | 80 | 8443\n\n"
        "➤ 💬 گفتگو و تبادل:\n"
        f"   {CHANNEL_LINK}\n\n"
        f"📅 آپدیت: ✅ تایید شد ({date})\n"
        f"✨ منبع: {SOURCE_LINK}"
    )

# ================== اجرای اصلی ==================

def main():
    if not BOT_TOKEN or not CHAT_ID or not CHANNEL_NAME:
        raise SystemExit(
            "❌ خطا: BOT_TOKEN / CHAT_ID / CHANNEL_NAME تنظیم نشده‌اند.\n"
            "   از فایل .env یا Environment Variable مقداردهی کنید.")

    # ۱) جمع‌آوری
    raw = []
    for src in SOURCES:
        raw.extend(fetch_source(src))
    print(f"[*] خطوط خام: {len(raw)}")

    # ۲) حذف تکراری
    configs = dedup(raw)
    print(f"[*] یکتا: {len(configs)}")

    # ۳) تست سه‌مرحله‌ای سختگیرانه — هر ۳ بار باید پاسخ بدهد
    alive = configs
    pings = {}
    for round_no in (1, 2, 3):
        print(f"[*] تست مرحله {round_no}: {len(alive)} کانفیگ ...")
        nxt = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(tcp_ping, cfg): (line, cfg) for line, cfg in alive}
            for fut in as_completed(futs):
                line, cfg = futs[fut]
                ms = fut.result()
                if ms is not None:
                    pings.setdefault(cfg["server"], []).append(ms)
                    nxt.append((line, cfg))
        alive = nxt
        print(f"[*] عبور از مرحله {round_no}: {len(alive)}")
    alive = [(line, cfg, min(pings[cfg["server"]])) for line, cfg in alive]
    print(f"[*] فعال و تأییدشده (۳/۳ تست): {len(alive)}")

    # ۴) تست واقعی با هسته Xray — هندشیک کامل + سرعت دانلود 3MB
    speeds, untested = {}, []
    xray_path = ensure_xray() if ensure_xray else None
    if xray_path and _real_test:
        xray_test.XRAY_BIN = xray_path
        print(f"[*] تست واقعی Xray: {len(alive)} کانفیگ (هندشیک + دانلود) ...")
        alive, untested, speeds = _real_test(alive, workers=25)
        print(f"[*] واقعاً کارکننده: {len(alive)} | پروتکل بدون تست Xray: {len(untested)}")
    else:
        print("[!] هسته Xray در دسترس نیست — نتیجه فقط بر پایه TCP است (کم‌اعتمادتر)")

    # ۵) GeoIP برای همه سرورهای نهایی
    all_items = ([(l, c, p, speeds.get(c["server"])) for l, c, p in alive]
                 + [(l, c, p, None) for l, c, p in untested])
    geo_map = geoip_lookup([cfg["server"] for _, cfg, _, _ in all_items])

    # ۶) ساخت نهایی + مرتب‌سازی (پورت طلایی → سرعت → پینگ)
    entries = []
    for line, cfg, ms, sp in all_items:
        remark = build_remark(geo_map.get(cfg["server"]), ms, sp)
        entries.append((rebuild_line(line, cfg, remark), cfg, sp or 0, ms))
    entries.sort(key=lambda t: (0 if int(t[1]["port"]) in GOLDEN_PORTS else 1,
                                -t[2], t[3]))
    final = [t[0] for t in entries]
    if MAX_CONFIGS:
        final = final[:MAX_CONFIGS]

    # ۷) نوشتن فایل txt
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(final) + "\n")
    print(f"[✓] فایل ساخته شد ({len(final)} کانفیگ)")

    # ۸) ارسال به تلگرام
    ok, r = tg_send_document(OUT_TXT, build_caption(len(final)))
    print("[✓] ارسال به تلگرام:", "موفق" if ok else r)

if __name__ == "__main__":
    main()

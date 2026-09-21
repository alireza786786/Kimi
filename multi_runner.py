import base64
import json
import os
import re
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests

# ==================== تنظیمات ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()
SOURCES_RAW = os.environ.get("SOURCES_JSON", "{}").strip()
CHANNEL_USERNAME = "@Goodbye_filtering"  # 👈 نام کانال شما

try:
    SOURCES = json.loads(SOURCES_RAW)
except Exception as e:
    print(f"❌ خطا در خواندن SOURCES_JSON: {e}")
    SOURCES = {}

TIMEOUT = 2.0
MAX_WORKERS = 100
MAX_LATENCY_MS = 500  # فقط زیر 500ms
GEO_BATCH_SIZE = 100

# ==================== توابع کمکی ====================
def get_flag(country_code):
    """تبدیل کد کشور به پرچم"""
    if country_code and len(country_code) == 2:
        return "".join(chr(127397 + ord(x.upper())) for x in country_code)
    return "🏳️"


def get_iran_time():
    """زمان فعلی ایران"""
    tehran_tz = timezone(timedelta(hours=3, minutes=30))
    return datetime.now(tehran_tz).strftime("%Y-%m-%d %H:%M")


def validate_environment():
    if not BOT_TOKEN:
        print("⚠️ BOT_TOKEN تنظیم نشده است.")
        return False
    if not CHAT_ID:
        print("⚠️ CHAT_ID تنظیم نشده است.")
        return False
    if not SOURCES:
        print("⚠️ SOURCES_JSON خالی است.")
        return False
    return True


# ==================== ساخت الگوی نام ====================
def build_config_name(protocol, country, country_code, city, ping_ms):
    """
    ساخت نام کانفیگ طبق الگوی درخواستی
    👉🆔@Goodbye_filtering📡🇩🇪®️Germany©️Frankfurt_am_Main🅿️ping:135ms⚡️Hysteria2
    """
    flag = get_flag(country_code)
    # تمیز کردن نام شهر (حذف فاصله و کاراکترهای خاص)
    city_clean = re.sub(r'[^A-Za-z0-9_]', '_', city) if city else "Unknown"
    city_clean = city_clean[:30]  # محدودیت طول
    # نام پروتکل با حرف بزرگ
    proto_name = {
        'vmess': 'Vmess',
        'vless': 'Vless',
        'trojan': 'Trojan',
        'hysteria2': 'Hysteria2',
        'hy2': 'Hysteria2',
        'ss': 'Shadowsocks'
    }.get(protocol.lower(), protocol.capitalize())
    name = (
        f"👉🆔{CHANNEL_USERNAME}"
        f"📡{flag}"
        f"®️{country}"
        f"©️{city_clean}"
        f"🅿️ping:{int(ping_ms)}ms"
        f"⚡️{proto_name}"
    )
    return name


# ==================== دیکود Base64 ====================
def try_decode_base64(text):
    text = text.strip()
    if not text:
        return []
    text = re.sub(r'\s+', '', text)
    padding = 4 - len(text) % 4
    if padding != 4:
        text += '=' * padding
    try:
        decoded = base64.b64decode(text).decode('utf-8', errors='ignore')
        return [line.strip() for line in decoded.split('\n') if line.strip()]
    except Exception:
        return []


# ==================== استخراج لینک‌ها ====================
def extract_links_from_text(text):
    patterns = [
        r'(?:vmess|vless|trojan|hy2|hysteria2|ss|ssr)://[^\s<>"\'`]+',
    ]
    links = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        links.extend(matches)
    return links


# ==================== تجزیه vmess ====================
def parse_vmess(link):
    try:
        b64_part = link[8:]
        padding = 4 - len(b64_part) % 4
        if padding != 4:
            b64_part += '=' * padding
        decoded = base64.b64decode(b64_part).decode('utf-8', errors='ignore')
        data = json.loads(decoded)
        return {
            'protocol': 'vmess',
            'host': data.get('add', ''),
            'port': int(data.get('port', 0)),
            'raw': link,
            'data': data
        }
    except Exception:
        return None


# ==================== تجزیه vless/trojan ====================
def parse_vless_trojan(link, protocol):
    try:
        # protocol://uuid@host:port?params#name
        match = re.match(
            rf'{protocol}://([^@]+)@([^:]+):(\d+)(\?[^#]*)?(?:#(.*))?',
            link,
            re.IGNORECASE
        )
        if match:
            return {
                'protocol': protocol,
                'host': match.group(2),
                'port': int(match.group(3)),
                'raw': link,
                'params': match.group(4) or '',
                'name': match.group(5) or ''
            }
    except Exception:
        pass
    return None


# ==================== تجزیه hysteria2 ====================
def parse_hysteria2(link):
    try:
        match = re.match(
            r'(?:hy2|hysteria2)://([^@]+)@([^:]+):(\d+)(\?[^#]*)?(?:#(.*))?',
            link,
            re.IGNORECASE
        )
        if match:
            return {
                'protocol': 'hysteria2',
                'host': match.group(2),
                'port': int(match.group(3)),
                'raw': link,
                'params': match.group(4) or '',
                'name': match.group(5) or ''
            }
    except Exception:
        pass
    return None


# ==================== تجزیه ss ====================
def parse_ss(link):
    try:
        rest = link[5:]
        if '@' in rest:
            auth, host_part = rest.split('@', 1)
            host_port = host_part.split('#')[0].split('?')[0]
            if ':' in host_port:
                host, port = host_port.rsplit(':', 1)
                return {
                    'protocol': 'ss',
                    'host': host,
                    'port': int(port),
                    'raw': link,
                    'name': ''
                }
    except Exception:
        pass
    return None


# ==================== تابع اصلی تجزیه ====================
def parse_proxy_link(link):
    link = link.strip()
    if not link:
        return None
    link_lower = link.lower()
    try:
        if link_lower.startswith('vmess://'):
            return parse_vmess(link)
        elif link_lower.startswith('vless://'):
            return parse_vless_trojan(link, 'vless')
        elif link_lower.startswith('trojan://'):
            return parse_vless_trojan(link, 'trojan')
        elif link_lower.startswith(('hy2://', 'hysteria2://')):
            return parse_hysteria2(link)
        elif link_lower.startswith('ss://'):
            return parse_ss(link)
    except Exception as e:
        print(f"⚠️ خطا در تجزیه: {e}")
    return None


# ==================== تست TCP ====================
def test_tcp_connection(host, port, timeout=TIMEOUT):
    try:
        start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        latency = (time.time() - start) * 1000
        if result == 0:
            return round(latency, 2)
    except Exception:
        pass
    return None


# ==================== Geo Lookup ====================
def fetch_geo_batch(ip_list):
    geo = {}
    if not ip_list:
        return geo
    for i in range(0, len(ip_list), GEO_BATCH_SIZE):
        batch = ip_list[i:i + GEO_BATCH_SIZE]
        try:
            r = requests.post(
                "http://ip-api.com/batch",
                json=[{"query": ip, "fields": "query,status,country,city,countryCode"} for ip in batch],
                timeout=10
            )
            if r.status_code == 200:
                for item in r.json():
                    if item.get("status") == "success":
                        geo[item["query"]] = {
                            "country": item.get("country", "Unknown"),
                            "city": item.get("city", "Unknown"),
                            "country_code": item.get("countryCode", "")
                        }
        except Exception as e:
            print(f"⚠️ خطا در geo lookup: {e}")
    return geo


# ==================== دریافت منابع ====================
def fetch_source(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        r = requests.get(url, timeout=15, headers=headers)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        print(f"⚠️ خطا در دریافت {url[:50]}...: {e}")
    return ""


# ==================== ساخت لینک جدید با نام ====================
def rebuild_link_with_name(proxy, new_name):
    """ساخت مجدد لینک با نام جدید"""
    protocol = proxy['protocol']
    raw = proxy['raw']
    try:
        if protocol == 'vmess':
            # vmess: تغییر ps در JSON
            data = proxy['data'].copy()
            data['ps'] = new_name
            new_b64 = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
            return f"vmess://{new_b64}"
        elif protocol in ('vless', 'trojan'):
            # vless/trojan: تغییر #name در انتها
            parts = raw.split('#', 1)
            base_url = parts[0]
            new_name_encoded = quote(new_name, safe='')
            return f"{base_url}#{new_name_encoded}"
        elif protocol == 'hysteria2':
            parts = raw.split('#', 1)
            base_url = parts[0]
            new_name_encoded = quote(new_name, safe='')
            return f"{base_url}#{new_name_encoded}"
        elif protocol == 'ss':
            # ss: ساختار پیچیده‌تر - فقط append name
            return f"{raw}#{quote(new_name, safe='')}"
    except Exception as e:
        print(f"⚠️ خطا در بازسازی لینک: {e}")
    return raw


# ==================== Main Pipeline ====================
def main():
    print("\n" + "=" * 60)
    print("🚀 V2Ray Runner v4.0 - شروع")
    print("=" * 60 + "\n")
    
    if not validate_environment():
        return
    
    # ۱. جمع‌آوری همه لینک‌ها
    print("📥 مرحله ۱: جمع‌آوری لینک‌ها از منابع...")
    all_links = []
    seen_links = set()  # برای حذف تکراری
    
    for group_name, urls in SOURCES.items():
        print(f"\n📂 گروه {group_name}: {len(urls)} منبع")
        for url in urls:
            print(f"  📥 {url[:60]}...")
            content = fetch_source(url)
            if not content:
                continue
            # اگه محتوا base64 باشه
            if not any(content.startswith(p) for p in ['vmess://', 'vless://', 'trojan://', 'hy2://', 'hysteria2://', 'ss://']):
                decoded_lines = try_decode_base64(content)
                if decoded_lines:
                    content = '\n'.join(decoded_lines)
            # استخراج لینک‌ها
            links = extract_links_from_text(content)
            for link in links:
                # حذف تکراری (بر اساس محتوای بدون #name)
                base_link = link.split('#')[0]
                if base_link not in seen_links:
                    seen_links.add(base_link)
                    all_links.append(link)
    
    print(f"\n✅ مجموع: {len(all_links)} لینک یکتا (تکراری‌ها حذف شدند)")
    
    if not all_links:
        print("❌ هیچ لینکی یافت نشد!")
        return
    
    # ۲. تجزیه لینک‌ها
    print("\n🔍 مرحله ۲: تجزیه لینک‌ها...")
    parsed_proxies = []
    for link in all_links:
        p = parse_proxy_link(link)
        if p and p['host'] and p['port']:
            # کلید یکتا برای حذف تکراری نهایی
            p['_unique_key'] = f"{p['protocol']}://{p['host']}:{p['port']}"
            parsed_proxies.append(p)
    
    # حذف تکراری‌ها بر اساس host:port
    seen_unique = set()
    unique_proxies = []
    for p in parsed_proxies:
        if p['_unique_key'] not in seen_unique:
            seen_unique.add(p['_unique_key'])
            unique_proxies.append(p)
    
    print(f"✅ {len(unique_proxies)} پروکسی یکتا (بر اساس host:port)")
    
    # ۳. تست TCP واقعی
    print(f"\n🧪 مرحله ۳: تست TCP واقعی روی {len(unique_proxies)} پروکسی...")
    
    def test_one(p):
        latency = test_tcp_connection(p['host'], p['port'])
        if latency is not None and latency <= MAX_LATENCY_MS:
            p['latency'] = latency
            return p
        return None
    
    alive_proxies = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(test_one, p): p for p in unique_proxies}
        for future in as_completed(futures):
            result = future.result()
            if result:
                alive_proxies.append(result)
    
    print(f"✅ {len(alive_proxies)} پروکسی زنده (زیر {MAX_LATENCY_MS}ms)")
    
    if not alive_proxies:
        print("❌ هیچ پروکسی زنده‌ای پیدا نشد!")
        return
    
    # ۴. اطلاعات جغرافیایی
    print(f"\n🌍 مرحله ۴: دریافت اطلاعات جغرافیایی...")
    ip_list = list(set(p['host'] for p in alive_proxies))
    geo = fetch_geo_batch(ip_list)
    for p in alive_proxies:
        info = geo.get(p['host'], {
            "country": "Unknown",
            "city": "Unknown",
            "country_code": ""
        })
        p['country'] = info['country']
        p['city'] = info['city']
        p['country_code'] = info['country_code']
        p['flag'] = get_flag(info['country_code'])
    
    # ۵. بازسازی لینک‌ها با نام جدید
    print(f"\n✏️ مرحله ۵: تغییر نام همه کانفیگ‌ها به الگوی کانال...")
    final_links = []
    for p in alive_proxies:
        new_name = build_config_name(
            p['protocol'],
            p['country'],
            p['country_code'],
            p['city'],
            p['latency']
        )
        new_link = rebuild_link_with_name(p, new_name)
        final_links.append(new_link)
    
    print(f"✅ {len(final_links)} کانفیگ با نام جدید ساخته شد")
    
    # ۶. ذخیره فایل
    output_file = "v2ray_configs.txt"
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(final_links))
        print(f"💾 فایل ذخیره شد: {output_file}")
    except Exception as e:
        print(f"❌ خطا در ذخیره فایل: {e}")
        return
    
    # ۷. ارسال به تلگرام
    print(f"\n📤 مرحله ۶: ارسال به تلگرام...")
    caption = (
        f"🚀 <b>{len(final_links)} کانفیگ زنده</b>\n"
        f"⏱ زمان: {get_iran_time()}\n"
        f"🎯 پینگ زیر {MAX_LATENCY_MS}ms\n"
        f"🌍 تست شده از همه کشورها\n"
        f"✨ {CHANNEL_USERNAME}"
    )
    send_to_telegram(caption, output_file)
    
    print("\n" + "=" * 60)
    print("✅ فرآیند با موفقیت تمام شد")
    print("=" * 60 + "\n")


def send_to_telegram(text, file_path=None):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ BOT_TOKEN یا CHAT_ID تنظیم نشده‌اند.")
        return False
    try:
        if file_path and os.path.exists(file_path):
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
            with open(file_path, 'rb') as f:
                files = {'document': f}
                data = {'chat_id': CHAT_ID, 'caption': text[:1024], 'parse_mode': 'HTML'}
                r = requests.post(url, files=files, data=data, timeout=30)
        else:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            data = {'chat_id': CHAT_ID, 'text': text[:4096], 'parse_mode': 'HTML'}
            r = requests.post(url, json=data, timeout=30)
        if r.status_code == 200:
            print("✅ ارسال موفق به تلگرام")
            return True
        else:
            print(f"❌ خطا در ارسال: {r.status_code} - {r.text[:200]}")
            return False
    except Exception as e:
        print(f"❌ خطا: {e}")
        return False


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ توقف (Ctrl+C)")
    except Exception as e:
        print(f"❌ خطای بحرانی: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

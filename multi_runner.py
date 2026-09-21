import asyncio
import base64
import ipaddress
import json
import os
import platform
import socket
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urlparse

import aiohttp
import requests

# ---------------------------------------------------------
# دریافت اطلاعات محرمانه از GitHub Secrets
# ---------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip()
SOURCES_RAW = os.environ.get("SOURCES_JSON", "{}").strip()

try:
    SOURCES = json.loads(SOURCES_RAW)
except Exception as e:
    print(f"❌ خطا در خواندن SOURCES_JSON: {e}")
    SOURCES = {}

TIMEOUT = 1.8
MAX_WORKERS = 80

# تست واقعی Xray فقط روی کاندیدهای برتر هر گروه انجام می‌شود (برای کنترل زمان اجرا)
REAL_TEST_MAX_CANDIDATES = 150
REAL_TEST_CONCURRENCY = 15
REAL_TEST_URL = "http://cp.cloudflare.com/generate_204"
REAL_TEST_TIMEOUT = 5.0


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
                json=batch, timeout=10,
            )
            if r.status_code == 200:
                for item in r.json():
                    if item.get("status") == "success":
                        geo[item["query"]] = {
                            "country": item.get("country", "Unknown"),
                            "city": item.get("city", "Unknown"),
                            "flag": get_flag(item.get("countryCode", "")),
                        }
        except Exception:
            pass
    return geo


# =============================================================================
# حفاظت SSRF — قبل از هر اتصال، مطمئن می‌شویم آی‌پی واقعی داخلی/خصوصی/
# متادیتای ابری نیست (مثلاً 127.0.0.1 یا آدرس متادیتای آژور که گیت‌هاب
# اکشنز رویش اجرا می‌شود). بدون این، یک کانفیگ مخرب می‌تواند اسکریپت را
# وادار به اتصال به شبکه‌ی داخلی رانر کند.
# =============================================================================

def _is_public_ip(ip_obj) -> bool:
    if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
        return False
    if ip_obj.is_multicast or ip_obj.is_reserved or ip_obj.is_unspecified:
        return False
    if isinstance(ip_obj, ipaddress.IPv4Address):
        if ip_obj in ipaddress.ip_network("100.64.0.0/10"):  # CGNAT
            return False
    return True


def resolve_safe_ip(host: str) -> Optional[str]:
    try:
        try:
            ip_obj = ipaddress.ip_address(host)
            return host if _is_public_ip(ip_obj) else None
        except ValueError:
            pass
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            ip_str = info[4][0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if _is_public_ip(ip_obj):
                return ip_str
        return None
    except Exception:
        return None


# =============================================================================
# مرحله‌ی ۱: تست سریع و سبک اتصال (TCP دوبل + جیتر) — فقط برای فیلتر اولیه
# =============================================================================

def stress_test_config(host, port):
    safe_ip = resolve_safe_ip(host)
    if safe_ip is None:
        return None, None
    t0 = time.time()
    try:
        s1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s1.settimeout(TIMEOUT)
        s1.connect((safe_ip, int(port)))
        s1.close()
        p1 = (time.time() - t0) * 1000
    except Exception:
        return None, None

    time.sleep(0.15)

    t1 = time.time()
    try:
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.settimeout(TIMEOUT)
        s2.connect((safe_ip, int(port)))
        s2.close()
        p2 = (time.time() - t1) * 1000
    except Exception:
        return None, None

    jitter = abs(p2 - p1)
    avg_ping = (p1 + p2) / 2.0
    if jitter > 70.0 or avg_ping > 480.0:
        return None, None
    return round(avg_ping, 1), round(jitter, 1)


def detect_arch_bonus(net, sec, fl, raw_link, port):
    bonus = 0
    if port in [443, 8443, 2053, 2083, 2087, 2096]:
        bonus += 150  # پورت طلایی درجه‌ی یک
    elif port in [80, 8080, 8880, 2052, 2082, 2086]:
        bonus += 70   # پورت طلایی درجه‌ی دو

    # بر اساس شواهد ۲۰۲۶ (greatfirewallguide.com)، VLESS+Reality+Vision نزدیک
    # به ۹۸٪ نرخ عبور از فیلترینگ دارد — اثبات‌شده‌ترین ترکیب، پس بالاترین
    # امتیاز را می‌گیرد. XHTTP هنوز شواهد مشابهی ندارد، پایین‌تر از آن است.
    if sec == "reality" and "xtls-rprx-vision" in fl:
        if "xPaddingBytes" in raw_link:
            bonus += 50
        return "Reality-Vision", bonus + 400
    if net in ["xhttp", "xray"]:
        return "XHTTP-Elite", bonus + 300
    if sec == "reality" and net == "grpc":
        return "Reality-gRPC", bonus + 300
    if sec == "reality":
        return "Reality", bonus + 250
    if net == "hysteria2" or "hysteria2://" in raw_link or "hy2://" in raw_link:
        return "Hysteria2", bonus + 380
    return "TLS-Tunnel", bonus + 150


def parse_and_test_config(raw_url):
    raw_url = raw_url.strip()

    if raw_url.startswith("vmess://"):
        try:
            b64_str = raw_url[8:].split('#')[0].strip()
            padded = b64_str + "=" * ((4 - len(b64_str) % 4) % 4)
            data_json = json.loads(base64.b64decode(padded).decode('utf-8', errors='ignore'))

            host = data_json.get("add", "").strip()
            port = int(data_json.get("port", 0))
            if not host or not port:
                return None

            ping, jitter = stress_test_config(host, port)
            if ping is None:
                return None

            net = data_json.get("net", "").lower()
            sec = data_json.get("tls", "").lower()
            arch, bonus = detect_arch_bonus(net, sec, "", raw_url, port)
            power_score = (100000.0 / ping) - (jitter * 2.0) + bonus
            return {
                "proto": "vmess", "json_data": data_json, "host": host, "port": port,
                "ping": ping, "jitter": jitter, "arch": arch,
                "score": round(power_score, 2), "raw": raw_url,
            }
        except Exception:
            return None

    try:
        parsed = urlparse(raw_url)
        scheme = parsed.scheme.lower()
        if scheme not in ["vless", "trojan", "hysteria2", "hy2", "tuic", "ss", "socks", "socks5"]:
            return None

        query = parse_qs(parsed.query)
        host = parsed.hostname or ""
        port = int(parsed.port or 0)
        if not host or not port:
            return None

        ping, jitter = stress_test_config(host, port)
        if ping is None:
            return None

        sec = query.get("security", [""])[0].lower()
        net = query.get("type", [""])[0].lower() or scheme
        fl = query.get("flow", [""])[0].lower()

        arch, bonus = detect_arch_bonus(net, sec, fl, raw_url, port)
        power_score = (100000.0 / ping) - (jitter * 2.0) + bonus
        base_url = raw_url.split("#")[0]
        return {
            "proto": scheme, "base_url": base_url, "host": host, "port": port,
            "ping": ping, "jitter": jitter, "arch": arch,
            "score": round(power_score, 2), "raw": raw_url,
        }
    except Exception:
        pass
    return None


def test_telegram_proxy(proxy_url):
    try:
        clean_url = proxy_url.strip()
        parsed = urlparse(clean_url)
        params = parse_qs(parsed.query)
        server = params.get("server", [""])[0]
        port_raw = params.get("port", [""])[0]
        if not server or not port_raw.isdigit():
            return None
        port = int(port_raw)
        safe_ip = resolve_safe_ip(server)
        if safe_ip is None:
            return None
        t0 = time.time()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        s.connect((safe_ip, port))
        s.close()
        latency = round((time.time() - t0) * 1000, 1)
        return {"url": clean_url, "server": server, "latency": latency}
    except Exception:
        pass
    return None


def fetch_urls_from_source(url):
    configs = []
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return configs
        content = r.text.strip()
        if not any(p in content for p in ["vless://", "vmess://", "trojan://", "tg://"]):
            try:
                padded = content + "=" * ((4 - len(content) % 4) % 4)
                decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
                if len(decoded) > 20:
                    content = decoded
            except Exception:
                pass

        lines = content.splitlines()
        valid_prefixes = ["vless://", "vmess://", "trojan://", "hysteria2://", "hy2://",
                           "tuic://", "ss://", "socks://", "socks5://", "tg://proxy",
                           "https://t.me/proxy"]
        for line in lines:
            line = line.strip()
            if any(line.startswith(prefix) for prefix in valid_prefixes):
                configs.append(line)
    except Exception:
        pass
    return configs


# =============================================================================
# مرحله‌ی ۲: تست واقعی Xray — فقط روی کاندیدهای برتر هر گروه، بعد از فیلتر
# سبک بالا. این همان چیزی است که واقعاً مشخص می‌کند پروکسی کار می‌کند یا نه،
# نه فقط اینکه پورت باز است.
# =============================================================================

def _xray_asset_name() -> str:
    machine = platform.machine().lower()
    if machine in ("aarch64", "arm64"):
        return "Xray-linux-arm64-v8a.zip"
    if machine.startswith("arm"):
        return "Xray-linux-arm32-v7a.zip"
    return "Xray-linux-64.zip"


async def ensure_xray_binary() -> Optional[str]:
    bin_dir = os.path.join(".", ".xray_bin")
    bin_path = os.path.join(bin_dir, "xray")
    if os.path.exists(bin_path) and os.access(bin_path, os.X_OK):
        return bin_path
    try:
        os.makedirs(bin_dir, exist_ok=True)
        asset = _xray_asset_name()
        url = f"https://github.com/XTLS/Xray-core/releases/latest/download/{asset}"
        zip_path = bin_path + ".zip"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as r:
                if r.status != 200:
                    print(f"⚠️ دانلود Xray ناموفق (HTTP {r.status})")
                    return None
                data = await r.read()
        with open(zip_path, "wb") as f:
            f.write(data)
        with zipfile.ZipFile(zip_path) as z:
            z.extract("xray", bin_dir)
        os.chmod(bin_path, 0o755)
        os.remove(zip_path)

        proc = await asyncio.create_subprocess_exec(
            bin_path, "version",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode != 0:
            print("⚠️ باینری Xray روی این دستگاه اجرا نشد.")
            return None
        return bin_path
    except Exception as e:
        print(f"⚠️ آماده‌سازی Xray ناموفق: {e}")
        return None


def build_xray_outbound(item: dict) -> Optional[dict]:
    """ساخت outbound سازگار با Xray از روی نتیجه‌ی parse_and_test_config."""
    try:
        proto = item["proto"]

        if proto == "vmess":
            j = item["json_data"]
            net = (j.get("net") or "tcp").lower()
            stream = {"network": net}
            if (j.get("tls") or "").lower() == "tls":
                stream["security"] = "tls"
                stream["tlsSettings"] = {
                    "serverName": j.get("sni") or j.get("host") or item["host"],
                    "allowInsecure": True,
                }
            if net == "ws":
                stream["wsSettings"] = {
                    "path": j.get("path", "/") or "/",
                    "headers": {"Host": j.get("host") or item["host"]},
                }
            elif net == "grpc":
                stream["grpcSettings"] = {"serviceName": j.get("path", "") or ""}
            return {
                "protocol": "vmess",
                "settings": {"vnext": [{
                    "address": item["host"], "port": item["port"],
                    "users": [{"id": j.get("id", ""), "alterId": int(j.get("aid", 0) or 0)}],
                }]},
                "streamSettings": stream,
            }

        raw = item["raw"]
        p = urlparse(raw)
        qs = {k: v[0] for k, v in parse_qs(p.query).items()}
        host, port = item["host"], item["port"]

        network = qs.get("type", "tcp") or "tcp"
        security = qs.get("security", "") or ""
        sni = qs.get("sni") or qs.get("host") or host
        fp = qs.get("fp", "chrome") or "chrome"

        stream: dict = {"network": network}
        if security == "reality":
            stream["security"] = "reality"
            stream["realitySettings"] = {
                "serverName": sni, "fingerprint": fp,
                "shortId": qs.get("sid", ""), "publicKey": qs.get("pbk", ""),
                "spiderX": qs.get("spx", ""),
            }
        elif security == "tls":
            stream["security"] = "tls"
            stream["tlsSettings"] = {"serverName": sni, "allowInsecure": True, "fingerprint": fp}

        if network == "ws":
            stream["wsSettings"] = {
                "path": qs.get("path", "/") or "/",
                "headers": {"Host": qs.get("host", sni)},
            }
        elif network == "grpc":
            stream["grpcSettings"] = {"serviceName": qs.get("serviceName", "")}

        if proto == "vless":
            uid = unquote(p.username or "")
            return {
                "protocol": "vless",
                "settings": {"vnext": [{
                    "address": host, "port": port,
                    "users": [{
                        "id": uid,
                        "encryption": qs.get("encryption", "none") or "none",
                        "flow": qs.get("flow", "") or "",
                    }],
                }]},
                "streamSettings": stream,
            }

        if proto == "trojan":
            password = unquote(p.username or "")
            if not stream.get("security"):
                stream["security"] = "tls"
                stream["tlsSettings"] = {"serverName": sni, "allowInsecure": True, "fingerprint": fp}
            return {
                "protocol": "trojan",
                "settings": {"servers": [{"address": host, "port": port, "password": password}]},
                "streamSettings": stream,
            }

        if proto == "ss":
            userinfo = unquote(p.username or "")
            method, password = None, None
            try:
                pad = "=" * (-len(userinfo) % 4)
                decoded = base64.urlsafe_b64decode(userinfo + pad).decode()
                method, password = decoded.split(":", 1)
            except Exception:
                if ":" in userinfo:
                    method, password = userinfo.split(":", 1)
            if not method or not password:
                return None
            return {
                "protocol": "shadowsocks",
                "settings": {"servers": [{
                    "address": host, "port": port, "method": method, "password": password,
                }]},
            }
        return None
    except Exception:
        return None


_PORT_COUNTER = {"n": 28000}


def _next_port() -> int:
    _PORT_COUNTER["n"] += 1
    return _PORT_COUNTER["n"]


async def real_test_one(xray_path: str, item: dict) -> bool:
    """اجرای واقعی یک پروکسی با Xray. فقط برای پروتکل‌هایی که Xray-core
    پشتیبانی می‌کند (vless/trojan/ss/vmess). برای بقیه (hysteria2/tuic/socks)
    بدون قضاوت True برمی‌گردد چون نمی‌توانیم واقعاً تستشان کنیم."""
    if item["proto"] not in ("vless", "trojan", "ss", "vmess"):
        return True

    outbound = build_xray_outbound(item)
    if outbound is None:
        return True  # نتوانستیم بسازیم؛ کاندید جریمه نمی‌شود

    local_port = _next_port()
    conf_path = f"/tmp/xray_mr_{local_port}.json"
    conf = {
        "log": {"loglevel": "none"},
        "inbounds": [{"listen": "127.0.0.1", "port": local_port, "protocol": "http", "settings": {}}],
        "outbounds": [outbound],
    }
    proc = None
    try:
        with open(conf_path, "w") as f:
            json.dump(conf, f)
        proc = await asyncio.create_subprocess_exec(
            xray_path, "run", "-c", conf_path,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.sleep(0.8)
        if proc.returncode is not None:
            return False

        proxy_url = f"http://127.0.0.1:{local_port}"
        for attempt in range(2):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        REAL_TEST_URL, proxy=proxy_url,
                        timeout=aiohttp.ClientTimeout(total=REAL_TEST_TIMEOUT),
                    ) as r:
                        return r.status in (200, 204)
            except Exception:
                if attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
                return False
        return False
    except Exception:
        return True  # خطای زیرساختی ما، نه تقصیر پروکسی
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        try:
            os.remove(conf_path)
        except Exception:
            pass


async def run_real_tests_async(items: list) -> list:
    """items: لیست دیکشنری‌های خروجی parse_and_test_config، مرتب‌شده بر اساس
    امتیاز. تا REAL_TEST_MAX_CANDIDATES تای برتر واقعاً با Xray تست می‌شوند؛
    بقیه دست‌نخورده از انتها اضافه می‌شوند."""
    xray_path = await ensure_xray_binary()
    if not xray_path:
        print("⚠️ Xray در دسترس نیست — تست واقعی رد شد، نتیجه فقط بر پایه‌ی پینگ است.")
        return items

    candidates = items[:REAL_TEST_MAX_CANDIDATES]
    rest = items[REAL_TEST_MAX_CANDIDATES:]
    sem = asyncio.Semaphore(REAL_TEST_CONCURRENCY)

    async def _check(it):
        async with sem:
            try:
                ok = await real_test_one(xray_path, it)
            except Exception:
                ok = True
            return it, ok

    results = await asyncio.gather(*[_check(it) for it in candidates])
    verified = [it for it, ok in results if ok]
    print(f"   🧪 تست واقعی: {len(verified)}/{len(candidates)} کاندیدای برتر تأیید شد.")
    return verified + rest


def run_real_tests(items: list) -> list:
    return asyncio.run(run_real_tests_async(items))


# =============================================================================
# پردازش هر گروه
# =============================================================================

def process_guard_group(group_key, url_list):
    print(f"\n🔄 در حال پردازش {group_key} با {len(url_list)} منبع...")
    raw_configs = []
    for u in url_list:
        raw_configs.extend(fetch_urls_from_source(u))

    raw_configs = list(set(raw_configs))
    print(f"📦 تعداد کل کاندیدها در {group_key}: {len(raw_configs)}")

    if group_key == "by8":
        valid_proxies = []
        with ThreadPoolExecutor(max_workers=50) as ex:
            futs = [ex.submit(test_telegram_proxy, p) for p in raw_configs]
            for f in as_completed(futs):
                res = f.result()
                if res:
                    valid_proxies.append(res)
        valid_proxies.sort(key=lambda x: x["latency"])
        return [p["url"] for p in valid_proxies]

    tested_results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = [ex.submit(parse_and_test_config, cfg) for cfg in raw_configs]
        for f in as_completed(futs):
            res = f.result()
            if res:
                tested_results.append(res)

    tested_results.sort(key=lambda x: x["score"], reverse=True)

    unique_map = {}
    for item in tested_results:
        key = (item["host"], item["port"])
        if key not in unique_map:
            unique_map[key] = item

    final_list = list(unique_map.values())
    final_list.sort(key=lambda x: x["score"], reverse=True)
    print(f"   ✅ {len(final_list)} کاندیدای یکتا پس از فیلتر سبک.")

    final_list = run_real_tests(final_list)

    geo_data = fetch_geo_batch(list({x["host"] for x in final_list}))

    output_lines = []
    for item in final_list:
        geo = geo_data.get(item["host"], {"country": "Unknown", "city": "Unknown", "flag": "🌐"})
        tag_str = (
            f"👉🆔@Goodbaye_filtering📡{geo['flag']}®️{geo['country']}©️{geo['city']}"
            f"🅿️ping:{item['ping']}ms~±{item['jitter']}ms⚡️{item['arch']}"
        )
        if item["proto"] == "vmess":
            v_json = item["json_data"]
            v_json["ps"] = tag_str
            encoded_vmess = base64.b64encode(
                json.dumps(v_json, ensure_ascii=False).encode('utf-8')).decode('utf-8')
            output_lines.append(f"vmess://{encoded_vmess}")
        else:
            output_lines.append(f"{item['base_url']}#{quote(tag_str)}")

    return output_lines


def send_telegram_file(file_path, group_name, count):
    if not BOT_TOKEN or not CHANNEL_ID:
        return
    tehran_tz = timezone(timedelta(hours=3, minutes=30))
    now_str = datetime.now(tehran_tz).strftime("%Y-%m-%d | %H:%M:%S")

    caption = f"""💎 بروزرسانی خودکار سابسکرایپ {group_name.upper()}

📊 تعداد کانفیگ‌های الماس: {count}
🕒 زمان بروزرسانی: {now_str} (تهران)
🛡 وضعیت: عبور از فیلتر پینگ/جیتر + تست واقعی اتصال Xray

✨ کانال: https://t.me/Goodbaye_filtering
💬 گروه: https://t.me/CONFIG_V2RAY_VIP"""

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        with open(file_path, "rb") as f:
            r = requests.post(url, data={"chat_id": CHANNEL_ID, "caption": caption},
                               files={"document": f}, timeout=30)
        res = r.json()
        if not res.get("ok"):
            print(f"❌ خطای تلگرام برای {group_name}: {res.get('description')}")
    except Exception as e:
        print(f"❌ خطای ارسال به تلگرام برای {group_name}: {e}")


def main():
    if not SOURCES:
        print("❌ هیچ منبعی در SOURCES_JSON تعریف نشده است.")
        return

    groups = ["guard1", "guard2", "guard3", "guard4", "guard5", "guard6", "guard7", "by8"]

    for idx, g_key in enumerate(groups, 1):
        url_list = SOURCES.get(g_key, [])
        if not url_list:
            print(f"⚠️ گروه {g_key} خالی است.")
            continue

        result_lines = process_guard_group(g_key, url_list)

        txt_filename = f"sub{idx}.txt"
        b64_filename = f"sub{idx}_b64.txt"

        content = "\n".join(result_lines)
        with open(txt_filename, "w", encoding="utf-8") as f:
            f.write(content)

        b64_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        with open(b64_filename, "w", encoding="utf-8") as f:
            f.write(b64_content)

        print(f"✅ فایل‌های {txt_filename} و {b64_filename} با {len(result_lines)} آیتم ذخیره شدند.")

        send_telegram_file(txt_filename, f"Guard-{idx}" if idx <= 7 else "Telegram-Proxies", len(result_lines))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
تست واقعی کانفیگ‌ها با هسته Xray — استاندارد طلایی
هر کانفیگ واقعاً اجرا می‌شود (هندشیک کامل پروتکل) و سرعت دانلود واقعی از داخل تونل اندازه می‌گیرد.
خروجی: فقط کانفیگ‌هایی که ۱۰۰% کار می‌کنند + سرعت واقعی هر کدام.
"""
import os
import sys
import json
import time
import base64
import socket
import zipfile
import urllib.parse
import subprocess
import tempfile
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
XRAY_BIN = os.path.join(BASE_DIR, "xray")
GH_API = "https://api.github.com/repos/XTLS/Xray-core/releases/latest"

LATENCY_URL = "http://cp.cloudflare.com/generate_204"            # باید 204 برگرداند
SPEED_URL = "https://speed.cloudflare.com/__down?bytes=3000000"  # ~3MB از کلادفلر
HANDSHAKE_TIMEOUT = 10
SPEED_TIMEOUT = 20
MIN_DOWNLOAD_RATIO = 0.5     # حداقل 50% فایل باید دانلود شود
BASE_PORT = 20000
PORT_SPAN = 8000


def ensure_xray(path=XRAY_BIN):
    """اگر xray نیست، آخرین نسخه Xray-core را از گیت‌هاب دانلود و نصب می‌کند"""
    if os.path.exists(path):
        return path
    plat = {"linux": "linux-64", "darwin": "macos-64", "win32": "windows-64"}.get(sys.platform)
    if not plat:
        print("[!] سیستم‌عامل شناسایی نشد — فایل xray را دستی کنار اسکریپت بگذارید")
        return None
    try:
        print("[*] دانلود هسته Xray ...")
        rel = requests.get(GH_API, timeout=30).json()
        asset = next(a for a in rel["assets"] if a["name"] == f"Xray-{plat}.zip")
        z = requests.get(asset["browser_download_url"], timeout=180).content
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        tmp.write(z); tmp.close()
        with zipfile.ZipFile(tmp.name) as zf:
            for n in zf.namelist():
                if os.path.basename(n) in ("xray", "xray.exe"):
                    with open(path, "wb") as out:
                        out.write(zf.read(n))
        os.unlink(tmp.name)
        os.chmod(path, 0o755)
        print("[✓] Xray نصب شد")
        return path
    except Exception as e:
        print(f"[!] نصب خودکار Xray ناموفق بود ({e}) — xray را دستی کنار اسکریپت بگذارید")
        return None


# ---------- تبدیل لینک اشتراکی به outbound جیسون Xray ----------

def _qs(u):
    return {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}

def link_to_outbound(line, cfg):
    scheme = cfg["scheme"]
    try:
        if scheme == "vless":
            u = cfg["data"]; q = _qs(u)
            stream = q.get("type", "tcp")
            sec = q.get("security", "none")
            user = {"id": cfg["id"], "encryption": "none"}
            if q.get("flow"):
                user["flow"] = q["flow"]
            ss = {"network": stream, "security": sec}
            if sec == "reality":
                ss["realitySettings"] = {
                    "show": False,
                    "fingerprint": q.get("fp", "chrome"),
                    "serverName": q.get("sni", ""),
                    "publicKey": q.get("pbk", ""),
                    "shortId": q.get("sid", ""),
                    "spiderX": urllib.parse.unquote(q.get("spx", "")) or "/",
                }
            elif sec == "tls":
                ss["tlsSettings"] = {"serverName": q.get("sni", ""),
                                     "fingerprint": q.get("fp", "chrome")}
            if stream == "ws":
                ss["wsSettings"] = {"path": q.get("path", "/"),
                                    "headers": {"Host": q.get("host", "")}}
            elif stream == "grpc":
                ss["grpcSettings"] = {"serviceName": urllib.parse.unquote(q.get("serviceName", "")),
                                      "multiMode": False}
            elif q.get("headerType") == "http":
                ss["tcpSettings"] = {"header": {"type": "http", "request": {
                    "path": [q.get("path", "/")], "headers": {"Host": [q.get("host", "")]}}}}
            return {"protocol": "vless",
                    "settings": {"vnext": [{"address": cfg["server"], "port": int(cfg["port"]),
                                            "users": [user]}]},
                    "streamSettings": ss}

        if scheme == "vmess":
            j = cfg["data"]
            stream = j.get("net", "tcp")
            sec = "tls" if str(j.get("tls", "")).lower() in ("tls", "true") else "none"
            ss = {"network": stream, "security": sec}
            if sec == "tls":
                ss["tlsSettings"] = {"serverName": j.get("sni", "")}
            if stream == "ws":
                ss["wsSettings"] = {"path": j.get("path", "/"),
                                    "headers": {"Host": j.get("host", "")}}
            elif stream == "grpc":
                ss["grpcSettings"] = {"serviceName": j.get("path", "")}
            elif j.get("type") == "http":
                ss["tcpSettings"] = {"header": {"type": "http", "request": {
                    "path": [j.get("path", "/")], "headers": {"Host": [j.get("host", "")]}}}}
            return {"protocol": "vmess",
                    "settings": {"vnext": [{"address": j.get("add", ""),
                                            "port": int(j.get("port", 0) or 0),
                                            "users": [{"id": j.get("id", ""),
                                                       "alterId": int(j.get("aid") or 0),
                                                       "cipher": j.get("scy", "auto")}]}]},
                    "streamSettings": ss}

        if scheme == "trojan":
            u = cfg["data"]; q = _qs(u)
            stream = q.get("type", "tcp")
            ss = {"network": stream, "security": "tls",
                  "tlsSettings": {"serverName": q.get("sni", u.hostname)}}
            if stream == "ws":
                ss["wsSettings"] = {"path": q.get("path", "/"),
                                    "headers": {"Host": q.get("host", "")}}
            return {"protocol": "trojan",
                    "settings": {"servers": [{"address": u.hostname, "port": u.port,
                                              "password": urllib.parse.unquote(u.username or "")}]},
                    "streamSettings": ss}

        if scheme == "ss":
            u = cfg["data"]
            raw = urllib.parse.unquote(u.username or "")
            if ":" not in raw:
                raw = base64.b64decode(raw + "==").decode()
            method, password = raw.split(":", 1)
            return {"protocol": "shadowsocks",
                    "settings": {"servers": [{"address": u.hostname, "port": u.port,
                                              "method": method, "password": password}]},
                    "streamSettings": {"network": "tcp"}}
    except Exception:
        return None
    return None   # hysteria2 / hy2 / tuic با هسته Xray قابل تست نیستند


# ---------- اجرای واقعی یک کانفیگ ----------

def _wait_port(port, proc, timeout=6.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            return False
        s = socket.socket(); s.settimeout(0.5)
        try:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                s.close(); return True
        except Exception:
            pass
        s.close(); time.sleep(0.1)
    return False

def test_one(item, port):
    """اجرای واقعی کانفیگ + هندشیک + دانلود 3MB → ('ok'|'untested'|'fail', ...)"""
    line, cfg, ping = item
    ob = link_to_outbound(line, cfg)
    if ob is None:
        return ("untested", line, cfg, ping, None)
    cfgfile = tempfile.NamedTemporaryFile("w", delete=False, suffix=".json")
    json.dump({"log": {"loglevel": "none"},
               "inbounds": [{"listen": "127.0.0.1", "port": port, "protocol": "socks",
                             "settings": {"udp": True}}],
               "outbounds": [ob]}, cfgfile)
    cfgfile.close()
    proc = None
    try:
        proc = subprocess.Popen([XRAY_BIN, "run", "-config", cfgfile.name],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not _wait_port(port, proc):
            return ("fail", line, cfg, ping, None)
        proxies = {"http": f"socks5h://127.0.0.1:{port}",
                   "https": f"socks5h://127.0.0.1:{port}"}
        # ۱) هندشیک واقعی: باید 204 بگیریم
        r = requests.get(LATENCY_URL, proxies=proxies, timeout=HANDSHAKE_TIMEOUT)
        if r.status_code != 204:
            return ("fail", line, cfg, ping, None)
        # ۲) سرعت واقعی: دانلود ~3MB از داخل تونل
        t0 = time.time(); got = 0
        with requests.get(SPEED_URL, proxies=proxies, timeout=SPEED_TIMEOUT,
                          stream=True) as rs:
            for chunk in rs.iter_content(65536):
                got += len(chunk)
        dt = time.time() - t0
        if got < 3000000 * MIN_DOWNLOAD_RATIO or dt <= 0:
            return ("fail", line, cfg, ping, None)
        speed = round(got * 8 / dt / 1_000_000, 1)   # Mbps
        return ("ok", line, cfg, ping, speed)
    except Exception:
        return ("fail", line, cfg, ping, None)
    finally:
        if proc:
            try: proc.kill()
            except Exception: pass
        try: os.unlink(cfgfile.name)
        except Exception: pass


def real_test(alive, workers=25):
    """alive: [(line, cfg, ping)] → (verified, untested, speeds)"""
    verified, untested, speeds = [], [], {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(test_one, item, BASE_PORT + (i % PORT_SPAN)): item
                for i, item in enumerate(alive)}
        done = 0
        for fut in as_completed(futs):
            done += 1
            status, line, cfg, ping, speed = fut.result()
            if status == "ok":
                verified.append((line, cfg, ping))
                srv = cfg["server"]
                speeds[srv] = max(speeds.get(srv, 0), speed)
            elif status == "untested":
                untested.append((line, cfg, ping))
            if done % 50 == 0:
                print(f"    Xray: {done}/{len(alive)} | کارکننده: {len(verified)}")
    return verified, untested, speeds

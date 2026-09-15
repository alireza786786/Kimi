# -*- coding: utf-8 -*-
"""
طھط³طھ ظˆط§ظ‚ط¹غŒ ع©ط§ظ†ظپغŒع¯â€Œظ‡ط§ ط¨ط§ ظ‡ط³طھظ‡ Xray â€” ط§ط³طھط§ظ†ط¯ط§ط±ط¯ ط·ظ„ط§غŒغŒ + ط¹غŒط¨â€ŒغŒط§ط¨غŒ ع©ط§ظ…ظ„
ظ‡ط± ع©ط§ظ†ظپغŒع¯ ظˆط§ظ‚ط¹ط§ظ‹ ط§ط¬ط±ط§ ظ…غŒâ€Œط´ظˆط¯ (ظ‡ظ†ط¯ط´غŒع© ع©ط§ظ…ظ„ ظ¾ط±ظˆطھع©ظ„) ظˆ ط³ط±ط¹طھ ط¯ط§ظ†ظ„ظˆط¯ ظˆط§ظ‚ط¹غŒ ط§ط² ط¯ط§ط®ظ„ طھظˆظ†ظ„ ط§ظ†ط¯ط§ط²ظ‡ ظ…غŒâ€Œع¯غŒط±ط¯.
ط¯ط± ظ¾ط§غŒط§ظ†طŒ ط®ظ„ط§طµظ‡ ط¯ظ„ط§غŒظ„ ط±ط¯ ط´ط¯ظ† ع©ط§ظ†ظپغŒع¯â€Œظ‡ط§ ع†ط§ظ¾ ظ…غŒâ€Œط´ظˆط¯ طھط§ ط¯ظ‚غŒظ‚ط§ظ‹ ط¨ظپظ‡ظ…غŒط¯ ع†ط±ط§ ظپغŒظ„طھط± ط´ط¯ظ†ط¯.
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
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
XRAY_BIN = os.path.join(BASE_DIR, "xray.exe" if sys.platform == "win32" else "xray")
GH_API = "https://api.github.com/repos/XTLS/Xray-core/releases/latest"

LATENCY_URL = "http://cp.cloudflare.com/generate_204"            # ط¨ط§غŒط¯ 204 ط¨ط±ع¯ط±ط¯ط§ظ†ط¯
SPEED_URL = "https://speed.cloudflare.com/__down?bytes=3000000"  # ~3MB ط§ط² ع©ظ„ط§ط¯ظپظ„ط±
HANDSHAKE_TIMEOUT = 10
SPEED_TIMEOUT = 20
MIN_DOWNLOAD_RATIO = 0.5     # ط­ط¯ط§ظ‚ظ„ 50% ظپط§غŒظ„ ط¨ط§غŒط¯ ط¯ط§ظ†ظ„ظˆط¯ ط´ظˆط¯
BASE_PORT = 20000
PORT_SPAN = 8000
DEBUG = os.getenv("DEBUG", "") == "1"

try:
    import socks  # noqa: F401  â€” ظˆط§ط¨ط³طھع¯غŒ requests[socks]
    SOCKS_OK = True
except ImportError:
    SOCKS_OK = False

# ط¢ظ…ط§ط± ط¯ظ„ط§غŒظ„ ط±ط¯ ط´ط¯ظ† â€” ط¨ط±ط§غŒ ط¹غŒط¨â€ŒغŒط§ط¨غŒ
FAIL_REASONS = Counter()
FAIL_SAMPLES = []


def _fail(reason, sample=""):
    FAIL_REASONS[reason] += 1
    if sample and len(FAIL_SAMPLES) < 10:
        FAIL_SAMPLES.append(f"{reason}: {sample[:200]}")
    return None


def ensure_xray(path=XRAY_BIN):
    """ط§ع¯ط± xray ظ†غŒط³طھطŒ ط¢ط®ط±غŒظ† ظ†ط³ط®ظ‡ Xray-core ط±ط§ ط§ط² ع¯غŒطھâ€Œظ‡ط§ط¨ ط¯ط§ظ†ظ„ظˆط¯ ظˆ ظ†طµط¨ ظ…غŒâ€Œع©ظ†ط¯"""
    if os.path.exists(path):
        return path
    plat = {"linux": "linux-64", "darwin": "macos-64", "win32": "windows-64"}.get(sys.platform)
    if not plat:
        print("[!] ط³غŒط³طھظ…â€Œط¹ط§ظ…ظ„ ط´ظ†ط§ط³ط§غŒغŒ ظ†ط´ط¯ â€” ظپط§غŒظ„ xray ط±ط§ ط¯ط³طھغŒ ع©ظ†ط§ط± ط§ط³ع©ط±غŒظ¾طھ ط¨ع¯ط°ط§ط±غŒط¯")
        return None
    try:
        print(f"[*] ط¯ط§ظ†ظ„ظˆط¯ ظ‡ط³طھظ‡ Xray ({plat}) ...")
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
        print("[âœ“] Xray ظ†طµط¨ ط´ط¯:", path)
        return path
    except Exception as e:
        print(f"[!] ظ†طµط¨ ط®ظˆط¯ع©ط§ط± Xray ظ†ط§ظ…ظˆظپظ‚ ط¨ظˆط¯ ({e}) â€” xray ط±ط§ ط¯ط³طھغŒ ع©ظ†ط§ط± ط§ط³ع©ط±غŒظ¾طھ ط¨ع¯ط°ط§ط±غŒط¯")
        return None


# ---------- طھط¨ط¯غŒظ„ ظ„غŒظ†ع© ط§ط´طھط±ط§ع©غŒ ط¨ظ‡ outbound ط¬غŒط³ظˆظ† Xray ----------

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
    except Exception as e:
        _fail("convert_error", repr(e))
        return None
    return None   # hysteria2 / hy2 / tuic ط¨ط§ ظ‡ط³طھظ‡ Xray ظ‚ط§ط¨ظ„ طھط³طھ ظ†غŒط³طھظ†ط¯


# ---------- ط§ط¬ط±ط§غŒ ظˆط§ظ‚ط¹غŒ غŒع© ع©ط§ظ†ظپغŒع¯ ----------

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
    """ط§ط¬ط±ط§غŒ ظˆط§ظ‚ط¹غŒ ع©ط§ظ†ظپغŒع¯ + ظ‡ظ†ط¯ط´غŒع© + ط¯ط§ظ†ظ„ظˆط¯ 3MB â†’ ('ok'|'untested'|'fail', ...)"""
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
        try:
            proc = subprocess.Popen([XRAY_BIN, "run", "-config", cfgfile.name],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            _fail("xray_start", repr(e))
            return ("fail", line, cfg, ping, None)
        if not _wait_port(port, proc):
            _fail("xray_no_listen", f"{cfg['scheme']} {cfg['server']}:{cfg['port']}")
            return ("fail", line, cfg, ping, None)
        proxies = {"http": f"socks5h://127.0.0.1:{port}",
                   "https": f"socks5h://127.0.0.1:{port}"}
        # غ±) ظ‡ظ†ط¯ط´غŒع© ظˆط§ظ‚ط¹غŒ: ط¨ط§غŒط¯ 204 ط¨ع¯غŒط±غŒظ…
        try:
            r = requests.get(LATENCY_URL, proxies=proxies, timeout=HANDSHAKE_TIMEOUT)
        except Exception as e:
            _fail("handshake_error", f"{cfg['server']} -> {e!r}")
            return ("fail", line, cfg, ping, None)
        if r.status_code != 204:
            _fail("handshake_bad_status", f"{cfg['server']} -> HTTP {r.status_code}")
            return ("fail", line, cfg, ping, None)
        # غ²) ط³ط±ط¹طھ ظˆط§ظ‚ط¹غŒ: ط¯ط§ظ†ظ„ظˆط¯ ~3MB ط§ط² ط¯ط§ط®ظ„ طھظˆظ†ظ„
        try:
            t0 = time.time(); got = 0
            with requests.get(SPEED_URL, proxies=proxies, timeout=SPEED_TIMEOUT,
                              stream=True) as rs:
                for chunk in rs.iter_content(65536):
                    got += len(chunk)
            dt = time.time() - t0
        except Exception as e:
            _fail("speed_error", f"{cfg['server']} -> {e!r}")
            return ("fail", line, cfg, ping, None)
        if got < 3000000 * MIN_DOWNLOAD_RATIO or dt <= 0:
            _fail("slow_download", f"{cfg['server']} got={got}B in {dt:.1f}s")
            return ("fail", line, cfg, ping, None)
        speed = round(got * 8 / dt / 1_000_000, 1)   # Mbps
        return ("ok", line, cfg, ping, speed)
    finally:
        if proc:
            try: proc.kill()
            except Exception: pass
        if not DEBUG:
            try: os.unlink(cfgfile.name)
            except Exception: pass


def real_test(alive, workers=25):
    """alive: [(line, cfg, ping)] â†’ (verified, untested, speeds) + ع¯ط²ط§ط±ط´ ط¹غŒط¨â€ŒغŒط§ط¨غŒ"""
    if not SOCKS_OK:
        raise RuntimeError(
            "â‌Œ ط¨ط³طھظ‡ PySocks ظ†طµط¨ ظ†غŒط³طھ ظˆع¯ط±ظ†ظ‡ ظ‡ظ…ظ‡ طھط³طھâ€Œظ‡ط§غŒ Xray ط³ط§ع©طھ ط´ع©ط³طھ ظ…غŒâ€Œط®ظˆط±ظ†ط¯!\n"
            "   ط§ط¬ط±ط§ ع©ظ†غŒط¯:  pip install 'requests[socks]'")
    FAIL_REASONS.clear(); FAIL_SAMPLES.clear()
    verified, untested, speeds = [], [], {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(test_one, item, BASE_PORT + (i % PORT_SPAN)): item
                for i, item in enumerate(alive)}
        done = 0
        for fut in as_completed(futs):
            done += 1
            try:
                status, line, cfg, ping, speed = fut.result()
            except Exception as e:
                _fail("worker_crash", repr(e))
                continue
            if status == "ok":
                verified.append((line, cfg, ping))
                srv = cfg["server"]
                speeds[srv] = max(speeds.get(srv, 0), speed)
            elif status == "untested":
                untested.append((line, cfg, ping))
            if done % 50 == 0:
                print(f"    Xray: {done}/{len(alive)} | ع©ط§ط±ع©ظ†ظ†ط¯ظ‡: {len(verified)}")
    total_fail = sum(FAIL_REASONS.values())
    print(f"[*] ط®ظ„ط§طµظ‡ طھط³طھ Xray â†’ ok={len(verified)} | untested={len(untested)} | ط±ط¯ ط´ط¯ظ‡={total_fail}")
    if FAIL_REASONS:
        print(f"    ط¯ظ„ط§غŒظ„ ط±ط¯: {dict(FAIL_REASONS)}")
    for s in FAIL_SAMPLES[:5]:
        print("    ظ†ظ…ظˆظ†ظ‡:", s)
    if DEBUG:
        print(f"    ط­ط§ظ„طھ DEBUG: ظپط§غŒظ„â€Œظ‡ط§غŒ ع©ط§ظ†ظپغŒع¯ xray ط¯ط± /tmp ط¨ط§ظ‚غŒ ظ…ط§ظ†ط¯ظ‡â€Œط§ظ†ط¯")
    return verified, untested, speeds

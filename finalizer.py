import os

# مسیرهای خروجی
BASE_DIR = os.path.join(os.path.dirname(__file__))  # مسیر پوشه‌ی Kimi
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
PROTOCOL_DIR = os.path.join(OUTPUT_DIR, "protocol")
COUNTRY_DIR = os.path.join(OUTPUT_DIR, "country")
GUARD_OUTPUT_DIR = os.path.join(BASE_DIR, "guards_output")  # مسیر درست پوشه‌ی ورودی

# ایجاد پوشه‌ها در صورت نداشتن
os.makedirs(PROTOCOL_DIR, exist_ok=True)
os.makedirs(COUNTRY_DIR, exist_ok=True)

# گام 3: خواندن همه فایل‌های guards
def read_all_configs():
    configs = []
    for file in os.listdir(GUARD_OUTPUT_DIR):
        if file.endswith(".txt"):
            with open(os.path.join(GUARD_OUTPUT_DIR, file), "r", encoding="utf-8") as f:
                configs.extend(f.read().splitlines())
    return configs

# گام 4: دسته‌بندی بر اساس پروتکل
def categorize_by_protocol(configs):
    protocol_map = {
        "vmess://": [],
        "vless://": [],
        "trojan://": []
    }
    for cfg in configs:
        for proto in protocol_map.keys():
            if cfg.startswith(proto):
                protocol_map[proto].append(cfg)
                break
    # ذخیره در فایل‌ها
    for proto, items in protocol_map.items():
        filename = os.path.join(PROTOCOL_DIR, proto.replace("://", "") + ".txt")
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(items))

# گام 5: دسته‌بندی بر اساس کشور (کد سه‌حرفی)
def categorize_by_country(configs):
    country_map = {}
    for cfg in configs:
        if "US" in cfg:
            country = "US"
        elif "DE" in cfg:
            country = "DE"
        elif "IR" in cfg:
            country = "IR"
        elif "NL" in cfg:
            country = "NL"
        else:
            country = "OTHER"
        country_map.setdefault(country, []).append(cfg)
    # ذخیره در فایل‌ها
    for country, items in country_map.items():
        filename = os.path.join(COUNTRY_DIR, country + ".txt")
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(items))

# اجرای مراحل
if __name__ == "__main__":
    configs = read_all_configs()
    categorize_by_protocol(configs)
    categorize_by_country(configs)

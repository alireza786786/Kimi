import os
import json

# پوشه ورودی
input_folder = "guards_output"

# پوشه خروجی
output_folder = "output"
os.makedirs(output_folder, exist_ok=True)

# دیکشنری کشورها
countries = {}

# خواندن فایل‌های ورودی
for filename in os.listdir(input_folder):
    path = os.path.join(input_folder, filename)

    # تشخیص کشور از نام فایل
    # مثال: JP-1.txt → JP
    country = filename.split("-")[0].upper()

    if country not in countries:
        countries[country] = {
            "v2ray": [],
            "clash": [],
            "singbox": []
        }

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # لینک‌های V2Ray نرمال
            if line.startswith(("vmess://", "vless://", "trojan://")):
                countries[country]["v2ray"].append(line)

            # فایل‌های Clash
            elif line.endswith(".yaml"):
                countries[country]["clash"].append(line)

            # فایل‌های sing-box
            elif line.endswith(".json"):
                countries[country]["singbox"].append(line)

# ذخیره خروجی‌ها
for country, data in countries.items():

    # V2Ray نرمال
    with open(f"{output_folder}/v2ray-{country}.txt", "w", encoding="utf-8") as f:
        for link in data["v2ray"]:
            f.write(link + "\n")

    # Clash
    with open(f"{output_folder}/clash-{country}.yaml", "w", encoding="utf-8") as f:
        for link in data["clash"]:
            f.write(link + "\n")

    # sing-box
    with open(f"{output_folder}/singbox-{country}.json", "w", encoding="utf-8") as f:
        json.dump(data["singbox"], f, indent=2, ensure_ascii=False)

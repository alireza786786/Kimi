import os
import re
import json

input_folder = "guards_output"
output_folder = "output"
os.makedirs(output_folder, exist_ok=True)

countries = {}

# الگوهای لینک‌ها
v2ray_pattern = re.compile(r"(vmess://[^\s]+|vless://[^\s]+|trojan://[^\s]+)")

for filename in os.listdir(input_folder):
    path = os.path.join(input_folder, filename)

    # تشخیص کشور از نام فایل
    country = filename.split("-")[0].upper()

    if country not in countries:
        countries[country] = {"v2ray": [], "clash": [], "singbox": []}

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

        # استخراج لینک‌های V2Ray از هرجای متن
        v2_links = v2ray_pattern.findall(content)
        countries[country]["v2ray"].extend(v2_links)

        # استخراج فایل‌های clash و singbox اگر داخل متن باشند
        for line in content.splitlines():
            line = line.strip()
            if line.endswith(".yaml"):
                countries[country]["clash"].append(line)
            elif line.endswith(".json"):
                countries[country]["singbox"].append(line)

# ذخیره خروجی‌ها
for country, data in countries.items():

    with open(f"{output_folder}/v2ray-{country}.txt", "w", encoding="utf-8") as f:
        for link in data["v2ray"]:
            f.write(link + "\n")

    with open(f"{output_folder}/clash-{country}.yaml", "w", encoding="utf-8") as f:
        for link in data["clash"]:
            f.write(link + "\n")

    with open(f"{output_folder}/singbox-{country}.json", "w", encoding="utf-8") as f:
        json.dump(data["singbox"], f, indent=2, ensure_ascii=False)

import os
import re

input_folder = "guards_output"
output_folder = "output"
os.makedirs(output_folder, exist_ok=True)

countries = {}

# الگوی لینک‌های V2Ray
v2ray_pattern = re.compile(r"(vmess://[^\s]+|vless://[^\s]+|trojan://[^\s]+)")

# خواندن فایل‌های ورودی
for filename in os.listdir(input_folder):
    path = os.path.join(input_folder, filename)

    # تشخیص کشور از نام فایل
    # مثال: IR-test.txt → IR
    country = filename.split("-")[0].upper()

    if country not in countries:
        countries[country] = {"v2ray": []}

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
        links = v2ray_pattern.findall(content)
        countries[country]["v2ray"].extend(links)

# ساخت خروجی‌ها
for country, data in countries.items():
    with open(f"{output_folder}/v2ray-{country}.txt", "w", encoding="utf-8") as f:
        for link in data["v2ray"]:
            f.write(link + "\n")

# ساخت README خودکار
readme_path = "README.md"
with open(readme_path, "w", encoding="utf-8") as readme:
    readme.write("## 🌍 By Country\n\n")
    readme.write("| Country | Nodes | V2Ray |\n")
    readme.write("|----------|--------|--------|\n")

    flags = {
        "JP": "🇯🇵", "US": "🇺🇸", "NL": "🇳🇱", "TW": "🇹🇼", "SG": "🇸🇬",
        "CA": "🇨🇦", "HK": "🇭🇰", "DE": "🇩🇪", "KR": "🇰🇷", "PL": "🇵🇱",
        "GB": "🇬🇧", "AU": "🇦🇺", "FR": "🇫🇷", "RO": "🇷🇴", "IN": "🇮🇳",
        "FI": "🇫🇮", "TH": "🇹🇭", "AE": "🇦🇪", "EE": "🇪🇪", "IT": "🇮🇹",
        "RU": "🇷🇺", "TR": "🇹🇷", "IR": "🇮🇷"
    }

    for country, data in sorted(countries.items()):
        count = len(data["v2ray"])
        flag = flags.get(country, "🏳️")
        readme.write(
            f"| {flag} {country} | {count} | "
            f"[v2ray-{country}.txt](output/v2ray-{country}.txt) |\n"
        )

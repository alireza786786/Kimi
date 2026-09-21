import os
import json

input_folder = "guards_output"
output_folder = "output/country"

os.makedirs(output_folder, exist_ok=True)

countries = {}

for filename in os.listdir(input_folder):
    path = os.path.join(input_folder, filename)
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # تشخیص کشور از نام فایل
            country = filename.split("-")[0].upper()

            if country not in countries:
                countries[country] = {
                    "clash": [],
                    "singbox": [],
                    "v2ray": []
                }

            if line.startswith("vmess://") or line.startswith("vless://") or line.startswith("trojan://"):
                countries[country]["v2ray"].append(line)

            elif line.endswith(".yaml"):
                countries[country]["clash"].append(line)

            elif line.endswith(".json"):
                countries[country]["singbox"].append(line)

# ذخیره خروجی‌ها
for country, data in countries.items():
    with open(f"{output_folder}/v2ray-{country}.txt", "w") as f:
        for link in data["v2ray"]:
            f.write(link + "\n")

    with open(f"{output_folder}/clash-{country}.yaml", "w") as f:
        for link in data["clash"]:
            f.write(link + "\n")

    with open(f"{output_folder}/singbox-{country}.json", "w") as f:
        json.dump(data["singbox"], f, indent=2)

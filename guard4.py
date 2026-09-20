import os
import json
import requests

# دریافت متغیرهای محیطی از سکرت‌های گیت‌هاب
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
SOURCES_JSON = os.environ.get("SOURCES_JSON")

OUTPUT_FILE = "subscription_guard4.txt"

def main():
    print("=== اجرای موتور Guard 4 ===")
    
    configs = []
    
    # بررسی و خواندن منابع از سکرت
    if SOURCES_JSON:
        try:
            sources = json.loads(SOURCES_JSON)
            print(f"تعداد {len(sources)} منبع دریافت شد.")
            
            for url in sources:
                try:
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        configs.append(response.text.strip())
                except Exception as e:
                    print(f"خطا در دریافت منبع {url}: {e}")
        except Exception as e:
            print(f"خطا در خواندن SOURCES_JSON: {e}")
    else:
        print("هشدار: SOURCES_JSON تعریف نشده است.")

    # ساخت فایل خروجی
    output_content = "\n".join(configs) if configs else "# Guard 4 Subscription List"
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(output_content)
        
    print(f"فایل خروجی با موفقیت در {OUTPUT_FILE} ذخیره شد.")

if __name__ == "__main__":
    main()

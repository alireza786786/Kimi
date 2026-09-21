import os

# مسیر پوشه خروجی
OUTPUT_DIR = "output"
PROTOCOL_DIR = os.path.join(OUTPUT_DIR, "protocol")
COUNTRY_DIR = os.path.join(OUTPUT_DIR, "country")

# ایجاد پوشه‌ها اگر وجود ندارند
os.makedirs(PROTOCOL_DIR, exist_ok=True)
os.makedirs(COUNTRY_DIR, exist_ok=True)

def main():
    print("شروع دسته‌بندی کانفیگ‌ها...")

if __name__ == "__main__":
    main()

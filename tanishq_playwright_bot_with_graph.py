import os
import re
import time
import io
import requests
import matplotlib.pyplot as plt
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ---------- CONFIG ----------
BOT_TOKEN = os.environ.get("TANI_BOT_TOKEN", "YOUR_BOT_TOKEN")
CHAT_ID = os.environ.get("TANI_CHAT_ID", "YOUR_CHAT_ID")
URL = "https://www.tanishq.co.in/gold-rate.html?lang=en_IN"

NAV_TIMEOUT = 30000
SELECTOR_TIMEOUT = 20000
RETRIES = 2
SAVE_DEBUG = False
# ----------------------------


def format_number_str(nstr):
    if not nstr:
        return nstr
    s = re.sub(r"[^\d\-]", "", nstr)
    if s == "":
        return nstr.strip()
    try:
        return f"₹{int(s):,}"
    except Exception:
        return nstr.strip()


def parse_22kt_table(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="goldrate-table-22kt")
    if not table:
        return None
    rows = table.find("tbody").find_all("tr")
    lines = ["📈 *Tanishq Gold Rates (22KT)*\n", "*Grammage | Today | Yesterday*", "---------------------------------"]
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 3:
            continue
        grammage = cols[0].get_text(strip=True)
        def first_price(td):
            for c in td.contents:
                if isinstance(c, str):
                    t = c.strip()
                    if t and any(ch.isdigit() for ch in t):
                        return t
            m = re.search(r"[\d,]+", td.get_text(" ", strip=True))
            return m.group(0) if m else td.get_text(" ", strip=True)
        today_raw = first_price(cols[1])
        yesterday_raw = first_price(cols[2])
        today = format_number_str(today_raw)
        yesterday = format_number_str(yesterday_raw)
        lines.append(f"{grammage} | {today} | {yesterday}")
    return "\n".join(lines)


def parse_historical_data(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="goldrate-history-table")
    if not table:
        return []
    rows = table.find("tbody").find_all("tr")
    data = []
    for row in rows:
        cols = row.find_all("td")
        if len(cols) >= 2:
            date = cols[0].get_text(strip=True)
            rate_text = re.sub(r"[^\d]", "", cols[1].get_text(strip=True))
            if date and rate_text:
                try:
                    data.append((date, int(rate_text)))
                except ValueError:
                    continue
    return data[::-1]


def generate_graph(data, filename="gold_history.png"):
    if not data:
        return None
    dates, rates = zip(*data)
    plt.figure(figsize=(8, 4))
    plt.plot(dates, rates, marker="o", color="#DAA520", linewidth=2)
    plt.title("Tanishq 22KT Gold Price Trend", fontsize=14, fontweight="bold")
    plt.xlabel("Date")
    plt.ylabel("Price (₹ per gram)")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(filename)
    plt.close()
    return filename


def send_telegram_message(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, data=payload, timeout=15)
        r.raise_for_status()
        print("✅ Telegram: message sent")
        return True
    except Exception as e:
        print("❌ Telegram send failed:", e)
        return False


def send_telegram_photo(token, chat_id, image_path, caption=None):
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with open(image_path, "rb") as photo:
            files = {"photo": photo}
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption
            r = requests.post(url, data=data, files=files, timeout=20)
            r.raise_for_status()
        print("✅ Telegram: graph sent")
        return True
    except Exception as e:
        print("❌ Telegram photo send failed:", e)
        return False


def fetch_page_html_with_playwright(url, save_debug=False):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1366, "height": 768})
        page = context.new_page()
        try:
            page.goto(url, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
            page.wait_for_selector("table.goldrate-table-22kt", timeout=SELECTOR_TIMEOUT)
            time.sleep(0.5)
            html = page.content()
            return html
        finally:
            if save_debug:
                with open("last_page.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
            context.close()
            browser.close()


def main():
    if BOT_TOKEN.startswith("YOUR_"):
        print("⚠️ Please set TANI_BOT_TOKEN and TANI_CHAT_ID environment variables.")
        return
    html = None
    for attempt in range(RETRIES + 1):
        try:
            print(f"➡️ Playwright fetch attempt {attempt + 1} ...")
            html = fetch_page_html_with_playwright(URL, save_debug=SAVE_DEBUG and attempt == RETRIES)
            if html and "Attention Required" not in html:
                break
        except Exception as e:
            print("❌ Fetch error:", e)
            time.sleep(2 ** attempt)
    if not html:
        print("❌ Could not fetch page.")
        return
    msg = parse_22kt_table(html)
    if msg:
        send_telegram_message(BOT_TOKEN, CHAT_ID, msg)
    hist_data = parse_historical_data(html)
    if hist_data:
        graph_file = generate_graph(hist_data)
        if graph_file:
            send_telegram_photo(BOT_TOKEN, CHAT_ID, graph_file, caption="📊 *Gold Price Trend*")


if __name__ == "__main__":
    # Render requires explicit Playwright install before running
    os.system("playwright install chromium > /dev/null 2>&1")
    main()

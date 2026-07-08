"""
Zara Stock Checker
-------------------
Ja proveruva dostapnosta na proizvodi od products.json i isprakja email
koga nekoj proizvod (ili konkretna golemina) stane dostapen za kupuvanje.

Chuva sostojba vo state.json za da ne isprakja isto izvestuvanje povekje pati.
"""

import json
import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).parent
PRODUCTS_FILE = BASE_DIR / "products.json"
STATE_FILE = BASE_DIR / "state.json"

OUT_OF_STOCK_HINTS = [
    "sold out",
    "agotado",
    "out of stock",
    "notify me",
    "известете ме",
    "нема на залиха",
    "распродадено",
]

IN_STOCK_HINTS = [
    "add to basket",
    "add to cart",
    "додади во кошничка",
    "додај во кошничка",
]


def load_json(path: Path, default):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def send_email(subject: str, body: str):
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD")
    to_email = os.environ.get("NOTIFY_EMAIL", gmail_user)

    if not gmail_user or not gmail_pass:
        print("EMAIL NOT SENT - missing GMAIL_USER / GMAIL_APP_PASSWORD secrets.")
        print(f"Subject: {subject}\n{body}")
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_email

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, [to_email], msg.as_string())
    print(f"Email sent: {subject}")


def accept_cookies_if_present(page):
    """Zara (i povekjeto EU sajtovi) prikazuvaat cookie banner koj mora da se zatvori
    pred ostatokot od stranata da e klikabilen/vidliv."""
    selectors = [
        "#onetrust-accept-btn-handler",
        "button#onetrust-accept-btn-handler",
        "button:has-text('Accept')",
        "button:has-text('Прифати')",
        "button:has-text('Accept all')",
    ]
    for sel in selectors:
        try:
            btn = page.query_selector(sel)
            if btn:
                btn.click(timeout=2000)
                page.wait_for_timeout(500)
                return True
        except Exception:
            continue
    return False


def check_product(page, product: dict):
    """
    Vrakja True (dostapno), False (nedostapno) ili None (ne mozevme da utvrdime -
    site strukturata mozebi se promenila, ili stranata ne se vcita kako sto ocekuvame).
    """
    url = product["url"]
    size = product.get("size")

    page.goto(url, timeout=60000, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    accept_cookies_if_present(page)
    page.wait_for_timeout(3000)

    title = page.title()
    content_lower = page.content().lower()
    print(f"  [debug] title='{title}' content_length={len(content_lower)}")
    if "captcha" in content_lower or "access denied" in content_lower:
        print("  [debug] IZGLEDA DEKA E BLOKIRANO (captcha/access denied vo stranata)")

    if size:
        buttons = page.query_selector_all("button, li, div[role='button']")
        for b in buttons:
            try:
                txt = (b.inner_text() or "").strip()
            except Exception:
                continue
            if txt == size or txt == size.upper():
                cls = (b.get_attribute("class") or "").lower()
                aria_disabled = b.get_attribute("aria-disabled")
                is_disabled = (
                    aria_disabled == "true"
                    or "disabled" in cls
                    or "out-of-stock" in cls
                    or "unavailable" in cls
                    or "sold" in cls
                )
                return not is_disabled
        return None
    else:
        if any(h in content_lower for h in OUT_OF_STOCK_HINTS):
            return False
        if any(h in content_lower for h in IN_STOCK_HINTS):
            return True
        return None


def main():
    products = load_json(PRODUCTS_FILE, [])
    state = load_json(STATE_FILE, {})

    if not products:
        print("Nema proizvodi vo products.json - dodadi gi tvoite Zara linkovi.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            locale="mk-MK",
        )
        page = context.new_page()

        for product in products:
            key = product["url"] + "|" + (product.get("size") or "any")
            prev_status = state.get(key)

            try:
                status = check_product(page, product)
            except Exception as e:
                print(f"Greska pri proverka na {product['name']}: {e}")
                continue

            print(f"{product['name']} ({product.get('size', 'any')}): {status}")

            if status is True and prev_status is not True:
                send_email(
                    subject=f"🟢 Достапно: {product['name']}",
                    body=(
                        f"'{product['name']}' "
                        f"(големина: {product.get('size', 'било која')}) "
                        f"сега е достапно за купување!\n\n{product['url']}"
                    ),
                )

            state[key] = status

        browser.close()

    save_json(STATE_FILE, state)


if __name__ == "__main__":
    sys.exit(main())

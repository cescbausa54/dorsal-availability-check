"""Vigila la pàgina de transferència de dorsals i avisa quan n'hi ha de disponibles.

Ús:
    python monitor.py            # una sola comprovació
    python monitor.py --loop     # comprova cada CHECK_INTERVAL segons durant LOOP_MINUTES minuts

Variables d'entorn:
    TARGET_URL          URL a vigilar (per defecte la de la Mitja 2027)
    CHECK_INTERVAL      segons entre comprovacions en mode --loop (per defecte 60)
    LOOP_MINUTES        minuts que dura el mode --loop (per defecte 9; 0 = infinit)
    NTFY_TOPIC          tema de https://ntfy.sh per rebre notificacions push al mòbil
    TELEGRAM_BOT_TOKEN  token d'un bot de Telegram (opcional)
    TELEGRAM_CHAT_ID    xat on el bot enviarà els avisos (opcional)
    SMTP_USER           compte de correu que envia l'avís (p. ex. el teu Gmail) (opcional)
    SMTP_PASSWORD       contrasenya d'aplicació d'aquest compte (opcional)
    EMAIL_TO            adreça on rebre l'avís (per defecte la mateixa SMTP_USER)
    SMTP_HOST/SMTP_PORT servidor SMTP (per defecte smtp.gmail.com:465)
    NOTIFY_ON_CHANGE    "1" per avisar també quan la pàgina canvia però no es detecten dorsals
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import smtplib
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

DEFAULT_URL = (
    "https://inscripciones.rpmsports.es/es/evento/"
    "hyundai-mitja-marato-barcelona-by-brooks-2027/transfer-registration"
)
URL = os.environ.get("TARGET_URL") or DEFAULT_URL
STATE_FILE = Path(__file__).parent / "state" / "state.json"

# Textos que indiquen que NO hi ha dorsals (es comparen sense accents i en minúscules).
NO_STOCK_PATTERNS = [
    r"no hay (ningun |ninguna )?(dorsal|dorsales|inscripcion|inscripciones|plazas)[^.]{0,40}disponible",
    r"no (hay|existen|se han encontrado) (dorsales|inscripciones|transferencias|resultados)",
    r"no hi ha (cap )?(dorsal|dorsals|inscripcio|inscripcions|places)",
    r"there are no (bibs|registrations|transfers)",
    r"no (bibs|registrations) (are )?available",
    r"agotad[oa]s?",
    r"sold out",
]

# Textos que indiquen que SÍ que hi ha dorsals a la venda.
STOCK_PATTERNS = [
    r"\bcomprar\b",
    r"\badquirir\b",
    r"anadir al carrito",
    r"dorsales? disponibles?:? *[1-9]",
    r"\bbuy\b",
    r"add to cart",
]

# Textos que indiquen que la pàgina no s'ha carregat bé (bloqueig, error, etc.).
ERROR_PATTERNS = [
    r"just a moment",
    r"checking your browser",
    r"access denied",
    r"error 50[0-9]",
    r"service unavailable",
]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).lower().strip()


def fetch_page_text(url: str) -> str:
    """Carrega la pàgina amb un navegador real (per si el contingut es genera amb JavaScript)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                locale="es-ES",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
                ),
            )
            page.goto(url, wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(2_000)
            return page.inner_text("body")
        finally:
            browser.close()


def classify(text: str) -> str:
    """Retorna 'available', 'none', 'error' o 'unknown'."""
    t = normalize(text)
    if len(t) < 50 or any(re.search(p, t) for p in ERROR_PATTERNS):
        return "error"
    if any(re.search(p, t) for p in NO_STOCK_PATTERNS):
        return "none"
    if any(re.search(p, t) for p in STOCK_PATTERNS):
        return "available"
    return "unknown"


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def send_ntfy(title: str, message: str) -> bool:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return False
    req = urllib.request.Request(
        f"https://ntfy.sh/{urllib.parse.quote(topic)}",
        data=message.encode(),
        headers={
            "Title": title.encode("ascii", "ignore").decode(),
            "Priority": "urgent",
            "Tags": "runner,rotating_light",
            "Click": URL,
        },
    )
    urllib.request.urlopen(req, timeout=20).read()
    return True


def send_telegram(title: str, message: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        return False
    data = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": f"{title}\n\n{message}"}
    ).encode()
    urllib.request.urlopen(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=20
    ).read()
    return True


def send_email(title: str, message: str) -> bool:
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    if not (smtp_user and smtp_password):
        return False
    email = EmailMessage()
    email["Subject"] = title
    email["From"] = smtp_user
    email["To"] = os.environ.get("EMAIL_TO") or smtp_user
    email.set_content(message)
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or "465")
    with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(email)
    return True


def notify(title: str, message: str) -> None:
    sent = False
    for sender in (send_telegram, send_email, send_ntfy):
        try:
            sent = sender(title, message) or sent
        except Exception as exc:  # un canal caigut no ha d'impedir els altres
            print(f"error enviant per {sender.__name__}: {exc}")

    if not sent:
        print("(cap canal de notificació configurat: defineix TELEGRAM_*, SMTP_* o NTFY_TOPIC)")
    print(f"AVÍS: {title} — {message}")


def check_once() -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        text = fetch_page_text(URL)
    except Exception as exc:  # xarxa, timeout...
        print(f"[{now}] error carregant la pàgina: {exc}")
        return "error"

    status = classify(text)
    digest = hashlib.sha256(normalize(text).encode()).hexdigest()
    state = load_state()
    print(f"[{now}] estat={status} hash={digest[:12]}")

    if status == "error":
        return status

    changed = digest != state.get("hash")
    if status == "available" and (state.get("status") != "available" or changed):
        snippet = normalize(text)[:300]
        notify("Dorsals disponibles a la Mitja!", f"Corre a comprar-lo: {URL}\n\n{snippet}")
    elif status == "unknown" and changed:
        # No reconeixem el text: millor avisar per si de cas.
        notify("La pàgina de dorsals ha canviat", f"Revisa-la manualment: {URL}")
    elif changed and state.get("hash") and os.environ.get("NOTIFY_ON_CHANGE") == "1":
        notify("La pàgina de dorsals ha canviat", f"Estat: {status}. {URL}")

    if changed or status != state.get("status"):
        save_state({"status": status, "hash": digest, "updated": now})
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()

    if not args.loop:
        return 0 if check_once() != "error" else 1

    interval = int(os.environ.get("CHECK_INTERVAL", "60"))
    minutes = float(os.environ.get("LOOP_MINUTES", "9"))
    deadline = time.monotonic() + minutes * 60 if minutes > 0 else float("inf")
    while True:
        check_once()
        if time.monotonic() + interval > deadline:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())

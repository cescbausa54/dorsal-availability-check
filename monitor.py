"""Vigila la pàgina de transferència de dorsals i avisa quan n'hi ha de disponibles.

La pàgina (MarketPlace) mostra una taula amb columnes Ref. / Tarifa / Importe /
Requiere validación. Quan no hi ha dorsals la taula és buida; cada fila és un dorsal a la venda.

Ús:
    python monitor.py            # una sola comprovació
    python monitor.py --loop     # comprova cada CHECK_INTERVAL segons durant LOOP_MINUTES minuts
    python monitor.py --heartbeat  # envia un correu confirmant que el monitor segueix actiu

Variables d'entorn:
    TARGET_URL          URL a vigilar (per defecte la de la Mitja 2027)
    CHECK_INTERVAL      segons entre comprovacions en mode --loop (per defecte 60)
    LOOP_MINUTES        minuts que dura el mode --loop (per defecte 9; 0 = infinit)
    SMTP_USER           compte de correu que envia l'avís (p. ex. el teu Gmail)
    SMTP_PASSWORD       contrasenya d'aplicació d'aquest compte
    EMAIL_TO            adreça on rebre l'avís (per defecte la mateixa SMTP_USER)
    SMTP_HOST/SMTP_PORT servidor SMTP (per defecte smtp.gmail.com:465)
    TELEGRAM_BOT_TOKEN  token d'un bot de Telegram (opcional)
    TELEGRAM_CHAT_ID    xat on el bot enviarà els avisos (opcional)
    NTFY_TOPIC          tema de https://ntfy.sh (opcional)
"""

from __future__ import annotations

import argparse
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

# Textos que indiquen que la pàgina no s'ha carregat bé (bloqueig, error, etc.).
ERROR_PATTERNS = [
    r"just a moment",
    r"checking your browser",
    r"access denied",
    r"error 50[0-9]",
    r"service unavailable",
]

# Files "buides" que algunes taules mostren quan no hi ha dades.
EMPTY_ROW_PATTERNS = [
    r"no hay (datos|registros|resultados|dorsales)",
    r"ningun (dato|registro|resultado)",
    r"no (data|records)",
]

# Retorna, per a cada taula que tingui una columna "Importe", les files del cos amb les cel·les.
EXTRACT_ROWS_JS = """
() => [...document.querySelectorAll('table')]
  .filter(t => /importe/i.test(t.innerText))
  .map(t => [...t.querySelectorAll('tr')]
    .filter(tr => tr.querySelector('td'))
    .map(tr => [...tr.querySelectorAll('td')].map(td => td.innerText.trim())))
"""


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).lower().strip()


def fetch_page(url: str) -> tuple[str, list[list[list[str]]]]:
    """Carrega la pàgina amb un navegador real i retorna (text, taules amb les seves files)."""
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
            return page.inner_text("body"), page.evaluate(EXTRACT_ROWS_JS)
        finally:
            browser.close()


def find_bibs(text: str, tables: list[list[list[str]]]) -> tuple[str, list[str]]:
    """Retorna (estat, dorsals). Estat: 'available', 'none' o 'error'."""
    if not tables:
        # Sense la taula no podem saber res: o la web ha fallat o ha canviat de format.
        t = normalize(text)
        reason = "bloqueig/error" if any(re.search(p, t) for p in ERROR_PATTERNS) else "no hi ha la taula"
        print(f"  ({reason})")
        return "error", []

    bibs = []
    for rows in tables:
        for cells in rows:
            line = " | ".join(c for c in cells if c)
            if not line or any(re.search(p, normalize(line)) for p in EMPTY_ROW_PATTERNS):
                continue
            bibs.append(line)
    return ("available" if bibs else "none"), bibs


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
        text, tables = fetch_page(URL)
    except Exception as exc:  # xarxa, timeout...
        print(f"[{now}] error carregant la pàgina: {exc}")
        return "error"

    status, bibs = find_bibs(text, tables)
    print(f"[{now}] estat={status} dorsals={len(bibs)}")
    if status == "error":
        return status

    state = load_state()
    new_bibs = [b for b in bibs if b not in state.get("bibs", [])]
    if new_bibs:
        listing = "\n".join(f"- {b}" for b in new_bibs)
        notify(
            "Dorsals disponibles a la Mitja!",
            f"Hi ha {len(new_bibs)} dorsal(s) nou(s) a la venda:\n{listing}\n\nCorre a comprar-lo: {URL}",
        )

    if status != state.get("status") or bibs != state.get("bibs", []):
        save_state({"status": status, "bibs": bibs, "updated": now})
    return status


def heartbeat() -> None:
    state = load_state()
    bibs = state.get("bibs", [])
    notify(
        "El monitor de dorsals segueix actiu",
        f"Tot en marxa. Dorsals a la venda ara mateix: {len(bibs)}.\n"
        f"Últim canvi detectat: {state.get('updated', 'cap encara')}.\n\n"
        f"Si deixes de rebre aquest correu cada dilluns, revisa la pestanya Actions del repo.\n{URL}",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--heartbeat", action="store_true")
    args = parser.parse_args()

    if args.heartbeat:
        heartbeat()
        return 0

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

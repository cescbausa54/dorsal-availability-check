# Monitor de dorsals – Mitja Marató de Barcelona 2027

Vigila cada minut la [pàgina de transferència de dorsals](https://inscripciones.rpmsports.es/es/evento/hyundai-mitja-marato-barcelona-by-brooks-2027/transfer-registration)
i t'envia un missatge de Telegram quan apareix algun dorsal disponible, amb l'enllaç per comprar-lo.

> **No compra automàticament.** La compra demana les teves dades i pagament, i els dorsals
> transferits solen volar en minuts: l'avís t'arriba amb l'enllaç directe perquè el compris tu.

## Com funciona

- Un GitHub Action s'executa cada 10 minuts i, dins de cada execució, comprova la pàgina **cada 60 s**
  durant 9 minuts (cobertura gairebé contínua).
- Carrega la pàgina amb un navegador real (Playwright/Chromium) i en classifica el text:
  - `none` – hi ha un missatge tipus "no hay dorsales disponibles" → no fa res.
  - `available` – apareixen botons/textos tipus "Comprar", "Añadir al carrito"... → **t'avisa**.
  - `unknown` – text que no reconeix → t'avisa cada vegada que la pàgina canvia, per si de cas.
  - `error` – bloqueig o error del servidor → no avisa (evita falses alarmes).
- L'últim estat es desa a `state/state.json` per no repetir avisos.

## Configuració (5 minuts)

1. **Crea un bot de Telegram:**
   - A Telegram, obre [@BotFather](https://t.me/BotFather) i envia `/newbot`. Tria un nom i un usuari acabat en `bot`.
   - Et donarà un **token** (tipus `123456789:AAH...`). Guarda'l.
   - Obre el teu bot nou i envia-li qualsevol missatge (p. ex. `hola`).
   - Al navegador, obre `https://api.telegram.org/bot<TOKEN>/getUpdates` (substituint `<TOKEN>`)
     i busca `"chat":{"id":123456789` → aquest número és el teu **chat_id**.
2. Al repo de GitHub: **Settings → Secrets and variables → Actions → New repository secret**:
   - `TELEGRAM_BOT_TOKEN` = el token.
   - `TELEGRAM_CHAT_ID` = el chat_id.
   - (Opcional) `NTFY_TOPIC` si també vols avisos per [ntfy](https://ntfy.sh).
3. **Actions → Vigila dorsals → Run workflow** per provar-ho. Al log veuràs `estat=...`.

Per provar que la notificació arriba: `TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python -c "import monitor; monitor.notify('Prova', 'Funciona!')"`.

## Ajustar la detecció

La primera vegada mira el log de l'Action. Si surt `estat=unknown` quan no hi ha dorsals, afegeix
el missatge exacte que mostra la web a `NO_STOCK_PATTERNS` dins de `monitor.py` (en minúscules i
sense accents). Si quan n'hi ha surt un altre text, afegeix-lo a `STOCK_PATTERNS`.

## Executar-ho en local

```bash
pip install -r requirements.txt
python -m playwright install chromium
TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... LOOP_MINUTES=0 CHECK_INTERVAL=30 python monitor.py --loop
```

## Notes

- El repo ha de ser **públic** perquè els minuts d'Actions siguin gratuïts il·limitats
  (en un repo privat, aquest ritme supera la quota gratuïta de 2.000 min/mes). No conté cap dada personal:
  els tokens van als *secrets*.
- GitHub desactiva els workflows programats si el repo no té activitat en 60 dies; si passa,
  reactiva'l des de la pestanya Actions.
- El cron de GitHub pot endarrerir-se uns minuts en hores punta.

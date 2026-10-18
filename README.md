# Monitor de dorsals – Mitja Marató de Barcelona 2027

Vigila cada minut la [pàgina de transferència de dorsals](https://inscripciones.rpmsports.es/es/evento/hyundai-mitja-marato-barcelona-by-brooks-2027/transfer-registration)
i t'envia un correu electrònic quan apareix algun dorsal disponible, amb l'enllaç per comprar-lo.

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

1. **Prepara el correu (Gmail):**
   - Activa la verificació en dos passos al teu compte de Google i crea una
     [contrasenya d'aplicació](https://myaccount.google.com/apppasswords) (16 lletres).
2. Al repo de GitHub: **Settings → Secrets and variables → Actions → New repository secret**:
   - `SMTP_USER` = el teu Gmail.
   - `SMTP_PASSWORD` = la contrasenya d'aplicació (no la teva contrasenya normal).
   - (Opcional) `EMAIL_TO` = adreça on vols rebre l'avís; per defecte, el mateix Gmail.
   - Amb un altre proveïdor, afegeix també `SMTP_HOST` i `SMTP_PORT` (SSL) al workflow.
   - (Opcional) També pot avisar per Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`)
     o [ntfy](https://ntfy.sh) (`NTFY_TOPIC`). Si no els poses, no s'utilitzen.
3. **Actions → Vigila dorsals → Run workflow** per provar-ho. Al log veuràs `estat=...`.

Per provar que la notificació arriba: `SMTP_USER=... SMTP_PASSWORD=... python -c "import monitor; monitor.notify('Prova', 'Funciona!')"`.

## Ajustar la detecció

La primera vegada mira el log de l'Action. Si surt `estat=unknown` quan no hi ha dorsals, afegeix
el missatge exacte que mostra la web a `NO_STOCK_PATTERNS` dins de `monitor.py` (en minúscules i
sense accents). Si quan n'hi ha surt un altre text, afegeix-lo a `STOCK_PATTERNS`.

## Executar-ho en local

```bash
pip install -r requirements.txt
python -m playwright install chromium
SMTP_USER=... SMTP_PASSWORD=... LOOP_MINUTES=0 CHECK_INTERVAL=30 python monitor.py --loop
```

## Notes

- El repo ha de ser **públic** perquè els minuts d'Actions siguin gratuïts il·limitats
  (en un repo privat, aquest ritme supera la quota gratuïta de 2.000 min/mes). No conté cap dada personal:
  els tokens van als *secrets*.
- GitHub desactiva els workflows programats si el repo no té activitat en 60 dies; si passa,
  reactiva'l des de la pestanya Actions.
- El cron de GitHub pot endarrerir-se uns minuts en hores punta.

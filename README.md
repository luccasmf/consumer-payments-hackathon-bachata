<p align="center">
  <img src="assets/felix-conversational-hackathon-logo.png" alt="Félix conversational hackathon — speech bubble and rocket on cyan" width="280" />
</p>

<p align="center"><strong>Félix conversational hackathon</strong><br /><em>Consumer payments · WhatsApp starter</em></p>

---

# Consumer payments hackathon — WhatsApp starter

**Build a bot people can actually text.** This repo is a small [FastAPI](https://fastapi.tiangolo.com/) backend wired to [Kapso](https://docs.kapso.ai/docs/introduction) so your team can **send and receive** WhatsApp messages in a sandbox, iterate locally, and focus on the *conversation*—not plumbing.

---

### What you get

- **Inbound:** Kapso hits your machine → you reply from `app/bot.py` (default demo: *“I just received: …Lets start building 🚀”*).
- **Outbound:** One-liner script + REST helper so you can ping your phone and see it in WhatsApp.
- **No database** — fewer moving parts; add storage when your idea needs it.

---

### Using Cursor?

Ask the agent: *“Help me set up `.env`, Kapso, ngrok, and start the server.”*  
The project loads **`.cursor/rules/kapso-hackathon-setup.mdc`** so everyone gets the same step-by-step path—including teammates who rarely touch the terminal.

---

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then fill values
uvicorn app.main:app --reload --port 8000
```

- Docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Health: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

## ngrok (required)

```bash
ngrok http 8000
```

Use the HTTPS host from ngrok to set Kapso webhook URL:

`https://<your-ngrok-host>/webhooks/whatsapp`

## Kapso setup notes

- Use your **sandbox** config.
- Copy `KAPSO_API_KEY` and `KAPSO_PHONE_NUMBER_ID` into `.env`.
- `KAPSO_VERIFY_TOKEN` in `.env` must match Kapso verify token field.
- In webhook events, **Message received** is sufficient for this starter.
- Leave message debouncing off unless you intentionally want batching.

## Demo outbound message

```bash
python -m app.send_demo_message --to "+1XXXXXXXXXX"
```

## Routes

- `GET /health`
- `GET /webhooks/whatsapp` (verification)
- `POST /webhooks/whatsapp` (inbound events)
- `POST /api/send-text` (manual outbound)

---

**Go build something people can text.**

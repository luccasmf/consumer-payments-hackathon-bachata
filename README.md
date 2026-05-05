

**Félix conversational hackathon**  
*Consumer payments · WhatsApp starter*

---

# Consumer payments hackathon — WhatsApp starter 🚀

**Build a bot people can actually text.** This repo is a small [FastAPI](https://fastapi.tiangolo.com/) backend wired to [Kapso](https://docs.kapso.ai/docs/introduction) so your team can **send and receive** WhatsApp messages in a sandbox, iterate locally, and focus on the *conversation*—not plumbing.

---

## Hackathon objective 🏆

Build a **conversational product** that solves a real problem.

- **Your mission:** Pick a problem, design a WhatsApp conversation flow, and ship a working demo.
- **Team goal:** Create the most useful, creative, and polished conversational experience you can in hackathon time.
- **How we pick a winner:** Everyone votes for their favorite project, and the team with the coolest project wins. 🎉

Think of this starter as your launchpad: focus your energy on the conversation, user value, and demo story.

---

## Project requirements ✅

To be considered a successful hackathon submission, teams should follow these rules:

1. **Vibe-code it with Cursor Agent:** Core implementation should be built through Cursor Agent workflows.
2. **Everyone contributes code:** Every teammate must push at least one change to the repository.
3. **Make it fun:** Build something that excites your team and is genuinely enjoyable to demo.

---

### What you get ✨

- **Inbound 💬:** Kapso hits your machine → you reply from `app/bot.py` (default demo: *“I just received: …Lets start building 🚀”*).
- **Outbound 📲:** One-liner script + REST helper so you can ping your phone and see it in WhatsApp.
- **No database 🧩:** Fewer moving parts; add storage when your idea needs it.

---

### Using Cursor? 🤖

Ask the agent: *“Help me set up `.env`, Kapso, ngrok, and start the server.”*  
The project loads **`.cursor/rules/kapso-hackathon-setup.mdc`** so everyone gets the same step-by-step path—including teammates who rarely touch the terminal.

#### How to use the rule directly

1. Open Cursor chat in this repo.
2. Ask for one step at a time (recommended for non-technical teammates).
3. Use prompts like:
  - `Walk me through setup and starting the bot`
  - `Help me fill .env for Kapso sandbox`
  - `Help me run uvicorn and ngrok`
  - `Help me configure the Kapso webhook URL and events`

The rule is auto-applied in this project, so you do **not** need to manually load it each time.

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

## Kapso account + sandbox setup (required) 🛠️

Before testing messages, each team member should do this in Kapso:

1. Create a Kapso account at [kapso.ai](https://kapso.ai/) and open the dashboard.
2. Open/create a **WhatsApp sandbox** configuration.
3. Add your personal phone number as an allowed sandbox/test recipient.
4. Copy these values from Kapso into `.env`:
  - `KAPSO_API_KEY`
  - `KAPSO_PHONE_NUMBER_ID`
5. Pick your own verify token (any secret phrase) and set:
  - `.env` → `KAPSO_VERIFY_TOKEN=<your token>`
  - Kapso webhook verify token field → same exact token
6. In webhook events, select **Message received** (enough for this starter). Leave debouncing off unless you explicitly want batching.

## ngrok (required) 🌍

```bash
ngrok http 8000
```

Use the HTTPS host from ngrok to set Kapso webhook URL:

`https://<your-ngrok-host>/webhooks/whatsapp`

## Kapso setup notes 🧠

- Use your **sandbox** config.
- Copy `KAPSO_API_KEY` and `KAPSO_PHONE_NUMBER_ID` into `.env`.
- `KAPSO_VERIFY_TOKEN` in `.env` must match Kapso verify token field.
- In webhook events, **Message received** is sufficient for this starter.
- Leave message debouncing off unless you intentionally want batching.

## Demo outbound message 🎯

```bash
python -m app.send_demo_message --to "+1XXXXXXXXXX"
```

## Routes 🗺️

- `GET /health`
- `GET /webhooks/whatsapp` (verification)
- `POST /webhooks/whatsapp` (inbound events)
- `POST /api/send-text` (manual outbound)

---

**Go build something people can text. Have fun and ship fast ⚡**
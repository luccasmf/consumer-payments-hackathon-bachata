---
title: "FX Rate Comparison API — Team Bachata vision"
date: 2026-05-06
tags:
  - felix-pago/hackathon
  - fx/remittances
  - project/bachata
aliases:
  - FX rate comparison across remittance providers
  - Remitly WU Tap Tap Send MoneyGram comparison API
generated_by: cursor-agent
---

# FX Rate Comparison API

Hackathon product note: an **API that compares FX rates / all-in costs** across remittance providers using public data (websites and, where relevant, Google search as part of discovery — not as the single source of truth).

**Relationship to this repo:** the backend remains FastAPI + WhatsApp via Kapso; this API can power replies from the bot in `app/bot.py`. See also [`AGENTS.md`](../AGENTS.md).

---

## Executive summary

| Aspect | Detail |
|--------|--------|
| **Goal** | Serve **apples-to-apples** FX comparisons across providers (same corridor + USD send amount). |
| **Input** | Destination (country → ISO currency) + **amount in USD** (multi-turn WhatsApp flow). |
| **Output** | Normalized comparison (`FxComparisonResponse`) + WhatsApp text; optional **7-day USD→currency chart** image. |
| **Data** | Rate-table HTTP feeds (**open.er-api**, Felix public endpoint) + **Monito compare** scrape (Playwright) per supported corridor. |

---

## Implementation in this repository

These notes track what **actually ships** in the hackathon codebase (May 2026):

| Piece | Location / behavior |
|--------|---------------------|
| **Conversation** | Two-turn flow in `app/services/rates_service.py`: keywords such as *rate*, *fx*, *tasa*, *cotización* → prompt for **country + USD amount**; user can answer in one message (*Mexico 250*) or split across messages. State is **in-memory per phone** (`_pending_rates`). |
| **Featured corridors** | Mexico (MXN), Colombia (COP), Guatemala (GTQ), Honduras (HNL), Dominican Republic (DOP), Brazil (BRL) — see `_FEATURED_CORRIDORS` and `_COUNTRY_ALIASES`. |
| **Rate-table providers** | `app/services/rates_providers/__init__.py`: **Spot anchor** via `OpenErApiProvider` ([open.er-api.com](https://open.er-api.com)) — internal id `open.er-api`, user label **General exchange price** — plus **Felix** public rates (`FelixPagoPublicProvider`). |
| **Remittance rows** | For currencies listed in `_CURRENCY_TO_ISO2`, `fetch_monito_quotes` adds **one row per Monito compare provider** (Remitly, Wise, WU, … depending on Monito). Other currencies still get the reference + Felix lines only. |
| **Caching** | When Redis is configured (`app/services/redis_client.py`), full comparisons are cached **5 minutes** under `fx:comparison:<currency>:<amount_normalized>`. |
| **Chart** | `get_history_chart_url` builds a **7-day** trend; the bot sends it as an **image** with the comparison as caption (or splits caption vs text if over WhatsApp limits — see `chart_reply_media_parts` in `app/bot.py`). |
| **Structured model** | `app/schemas/fx_comparison.py` — `FxComparisonResponse` with `best_provider`, `spread_rate`, `advantage_vs_worst` among **remittance** quotes only (excludes the default spot feed). |

**HTTP endpoint (debug / integration):** `POST /api/monito/compare` — runs the Monito Playwright scrape only (can take tens of seconds; requires Chromium). There is no separate public `GET /compare` for the full bundled comparison yet; the **primary surface is WhatsApp** via `handle_rates_message`.

---

## Product objective

Ship an **API** that **compares FX** across providers so the product (e.g. WhatsApp chat) can answer *“for your case, X beats Y”* with fresh data.

---

## Target providers (v1)

Initial coverage goals:

- Remitly  
- Western Union  
- Tap Tap Send  
- MoneyGram  

> **Note:** Each has different flows (corridors, limits, new-user promos). The comparison must document **which assumptions** were used per provider.

---

## Quote dimensions (scenarios)

Scrapers or extraction paths must be able to distinguish — or parameterize — at least:

| Dimension | Description |
|-----------|-------------|
| **New users** | Promotions / first-time transfer. |
| **Returning users** | Standard pricing without welcome promo. |
| **Amount ≥ USD 500** | Quote above the threshold (USD 500 or equivalent). |
| **Amounts below USD 500** | Quote below the threshold. |

These dimensions can map to future API **query params** (e.g. `user_segment=new|returning`, `amount_bucket=below_500|above_500`) and to separate scraping jobs if each combination needs its own session.

---

## Technical approach

1. **Per-provider scraping**  
   - Scripts or agents that drive each site’s public quote flow.  
   - **browser-use** (or similar orchestration) to turn browser interaction into reproducible steps behind HTTP endpoints.

2. **API layer**  
   - FastAPI: operational routes under `/api` (e.g. `POST /api/monito/compare` for raw Monito rows).  
   - Full comparison + Redis TTL + chart wiring live in **`rates_service`** for the bot path.  
   - Short TTL cache + UTC timestamps on rendered messages.

3. **“Information on Google”**  
   - Reasonable use: find official URLs, support numbers, or **official** rate pages.  
   - Do not replace direct quote scraping when the comparison depends on the user’s currency pair and corridor.

---

## WhatsApp integration (hackathon)

- The user triggers the flow with **rate-related keywords** (English or Spanish); the bot asks for **destination country** and **USD amount** if either is missing.  
- Parsed quotes compare **remittance estimates** (Monito rows when available) against a **mid-market reference** line from the default spot feed (**General exchange price**).  
- Canonical handlers: [`app/bot.py`](../app/bot.py) → [`app/services/rates_service.py`](../app/services/rates_service.py).

### Bot reply format (implemented)

Rendered by `format_comparison_response` — **all-in estimates**, destination currency varies by corridor (not hard-coded to MXN):

```
Today *$<amount> USD* to *<Country>* (*<CODE>*) converts like this — all-in, no surprises:

*General exchange price* → *<total> <CODE>* — mid-market reference (chart)

*Remittance estimates*

1️⃣ *<Provider>* → *<total> <CODE>* — all-in estimate
2️⃣ *<Provider>* → ...
...

⚠️ *<Worst provider>* delivers the least today — *<total> <CODE>* for this send amount.

*What works best for you?*
• *Most <CODE> received*: <Provider>
• *Next best*: <Provider>
• (*Third bullet*: also competitive, or WhatsApp/Félix highlight when relevant)

The difference between the best and worst is *<diff> <CODE>* per *<amount> USD* you send.

_Updated YYYY-MM-DD HH:MM UTC (cached)_
```

When a chart is generated, the bot appends a short **📊** footer explaining the 7-day USD→currency trend (mid-market baseline).

**Formatting rules (current code):**

- **Reference line:** one row for **General exchange price** (open.er-api), labeled mid-market / chart — **not** mixed into the numbered remittance ranking.  
- **Remittance block:** sorted by **total received in destination currency** (best first). Lines use emoji ranks **1️⃣–🔟**, then plain numerals beyond ten.  
- Each remittance line ends with **— all-in estimate** (fee and delivery are **not** broken out per row yet — that richer copy remains a product stretch goal).  
- **⚠️** calls out the **lowest remittance total** for the corridor.  
- **Quick picks:** up to three bullets (`Most … received`, `Next best`, optional third).  
- **Spread line:** absolute **destination-currency** gap between best and worst **remittance** quote.  
- **Footer:** `_Updated … UTC_` plus ` (cached)` when served from Redis.

### Richer copy (product target, not yet in code)

A future iteration can mirror marketing-style lines (**fee**, **delivery SLA**) per provider when we have reliable structured fields. Until then, treat Monito-derived amounts as **single-number estimates**:

```
1️⃣ <Provider> → $<amount> MXN — free, in minutes
```

---

### Example (illustrative — richer UX target)

The following block shows the **intended** density of information once fee + speed are available from scrapers or APIs; it does **not** match the current bot string verbatim:

```
Today $100 USD converts as follows (all-in, no surprises):

1️⃣ MoneyGram → $1,778 MXN — free, up to 1 day
...
⚠️ XE charges an extra $3 USD and only delivers $1,656 MXN — the worst option today.
...
The gap between best and worst is $122 MXN per $100 you send.
```

> **Localization:** WhatsApp copy can follow the same block structure in Spanish; keep ordering aligned with `FxComparisonResponse` fields for API parity.

---

## Risks and compliance

- **Terms of use** on each site: confirm whether automated scraping is allowed; prefer official APIs/partners when available.  
- **Fragility:** DOM changes break scrapers — maintain selectors and per-provider tests.  
- **Accuracy:** always surface **estimates** and quote date/time.

---

## Suggested Obsidian map (if you copy this note into your vault)

Practices when moving it into your vault:

| Practice | Application |
|----------|---------------|
| **Location** | e.g. `FelixPago/Projects/` or your hackathon folder. |
| **Wiki links** | Link atomic notes: `[[Remitly scraping notes]]`, `[[WU quote flow]]`, `[[browser-use eval]]` from here with `[[…]]`. |
| **MOC** | A *Map of Content* index such as `[[Hackathon Bachata MOC]]` linking this vision, `AGENTS`, demo decisions. |
| **Tags** | Keep `felix-pago/hackathon` and `project/bachata`; avoid duplicating what the folder already encodes. |
| **Daily link** | In that day’s daily: `- [[FX Rate Comparison API]] — idea/demo checkpoint.` |

**Relative links in GitHub** (work in-repo): [AGENTS.md](../AGENTS.md), [KICKOFF.md](../KICKOFF.md).

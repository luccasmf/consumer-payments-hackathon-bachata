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
| **Goal** | Serve **apples-to-apples** FX comparisons across providers (same usage scenario). |
| **Input** | Scenario parameters: user type, amount, corridors/currency pairs as we define them. |
| **Output** | Comparable JSON (rate, fee, estimated total cost, timestamp, provider). |
| **Data** | Controlled scraping of provider sites + normalization; **browser-use** to automate browsing when HTML is dynamic. |

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
   - FastAPI: endpoints such as `GET /compare` or `POST /quote` returning normalized comparisons.  
   - Short TTL cache + timestamps to avoid hammering third-party sites.

3. **“Information on Google”**  
   - Reasonable use: find official URLs, support numbers, or **official** rate pages.  
   - Do not replace direct quote scraping when the comparison depends on the user’s currency pair and corridor.

---

## WhatsApp integration (hackathon)

- The user sends **origin/destination country, amount, profile** (new vs returning if we capture it) over WhatsApp.  
- The bot calls comparison logic (local or internal service) and replies with a **short ranking** and disclaimers.  
- Canonical message handling: [`app/bot.py`](../app/bot.py).

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

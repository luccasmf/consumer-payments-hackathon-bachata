---
name: obsidian-hackathon-docs
description: >-
  Exports or mirrors repository documentation into each teammate's local
  Obsidian vault after resolving where that vault lives on disk. Use when the
  user wants docs updated in Obsidian, copied from docs/ or project notes into
  a personal vault, mentions Obsidian vault path, local notes path, or syncing
  Bachata / hackathon documentation outside the repo.
---

# Docs → Obsidian (per-person vault location)

Everyone keeps their vault at a **different path**. Before creating or overwriting `.md` files outside this repo, resolve **where** to save them.

## 1. Resolve the vault path (required if unknown)

**Preferred:** read `OBSIDIAN_VAULT_PATH` from the user’s `.env` (same key as in `.env.example`). If it is set to a non-empty value, verify the path exists, then use it as the base directory.

**If missing or empty, ask the user explicitly:**

> What is the **absolute path** to your Obsidian vault, or to the **folder inside the vault** where you want Bachata hackathon notes for this project?  
> macOS example: `/Users/<you>/Obsidian/MyVault` or `…/MyVault/FelixPago/Projects`.

**Do not assume** paths from other projects or from a maintainer’s machine. If the user already pasted the path in the message, use it and confirm briefly.

After the user provides a path, suggest adding it to `.env` as `OBSIDIAN_VAULT_PATH=...` for next time (never commit `.env`).

## 2. Choose a destination inside the vault

By default suggest a project-specific subfolder, for example:

`<VAULT>/FelixPago/Projects/Bachata-Hackathon/`  
or  
`<VAULT>/<area>/Hackathons/Bachata/`

The user decides (personal vs work area, folder naming, etc.).

## 3. What to sync from this repo

| Repo source | Typical use in Obsidian |
|---------------|-------------------------|
| `docs/` | Product/API notes (e.g. `docs/FX Rate Comparison API.md`) |
| `AGENTS.md`, `README.md`, `KICKOFF.md` | Context copies for meetings or demo (optional; warn about duplication) |

**Rules:**

- **Copy or write** the `.md` files to the agreed path; keep Obsidian-friendly filenames (spaces OK; avoid `:` `?` `/` in names).
- If the user wants a **summary** instead of a full copy, say so and produce a new note with links to the repo (`https://github.com/...`) when relevant.
- **Frontmatter:** if the vault uses Properties, a minimal block helps later (align property names with the user’s conventions):

```yaml
---
date: YYYY-MM-DD
tags:
  - felix-pago/hackathon
generated_by: cursor-agent
source: "[[repo consumer-payments-hackathon-bachata]]"
---
```

## 4. Verification

- After writing, confirm the final file path as an absolute path the user can open in Obsidian.
- Do not run destructive commands against the vault without explicit confirmation.

## 5. Other skills

- For **detailed** Axelio vault conventions (FelixPago folders, meetings, wiki-links), combine with the personal skill `obsidian-best-practices` at `~/.cursor/skills/obsidian-best-practices/` **only** when that vault applies to the user.

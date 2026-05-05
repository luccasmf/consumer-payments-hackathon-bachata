# Contributing (hackathon workflow)

**This file is optional.** Use it if your team wants a shared playbook for Git + PRs. You can branch directly on the canonical repo or use a fork—both are valid (see below).

This repo is meant for **fast collaboration** while many people **vibe-code with Cursor Agent**. The goal is to ship a working WhatsApp demo without merge-conflict chaos.

## Default model: one team branch from `main` (you own it)

When everyone can push to the **same** GitHub repo, we recommend:

- **Each hackathon team has exactly one long-lived branch** created from `main`. **That branch is yours**—do all day-to-day work there so you don’t collide with other teams on `main`.
- **Name it after your team** so it’s obvious who owns it, e.g. `team-bananas`, `team-ledger`, `team-payments-cat`.
- **All teammates** check out **that same branch**, pull before coding, commit, and push to it.
- **Merge to `main`** when you have something stable: open a **pull request** from your team branch → `main` (small PRs are still better than one giant merge at the deadline).
- **Stay current with `main`:** regularly merge `main` into your team branch (`git checkout team-…` then `git merge main`) so you don’t drift.

### Create your team branch (once per team)

Pick a **single slug** (lowercase, hyphens OK). One person runs:

```bash
git checkout main
git pull origin main
git checkout -b team-<your-slug>
git push -u origin team-<your-slug>
```

Everyone else:

```bash
git fetch origin
git checkout team-<your-slug>
```

### Day-to-day on the team branch

```bash
git checkout team-<your-slug>
git pull origin team-<your-slug>    # or: git pull while on that branch
# … make changes …
git add -A && git commit -m "Describe the change"
git push origin team-<your-slug>
```

**Avoid** each person creating their own unrelated long-lived branch unless organizers say otherwise—use **one** team branch so ownership stays clear.

### Optional: tiny local branches for spikes

If someone needs a quick experiment, they can use `team-<slug>/<topic>` and merge it back into the team branch via PR—but the **canonical line of work** should still be **the team’s main branch** above.

## Alternative: fork the starter (optional)

Use a **fork** when you want isolation (e.g. only your fork is writable, or you prefer PRs into the “official” repo).

1. On GitHub, open this repository and click **Fork** (fork into your account or a team org).
2. Clone **your fork** (not the original):
   ```bash
   git clone git@github.com:<your-username>/consumer-payments-hackathon.git
   cd consumer-payments-hackathon
   ```
3. Add the original repo as **`upstream`** so you can pull starter updates:
   ```bash
   git remote add upstream git@github.com:alex-felixpagos/consumer-payments-hackathon.git
   ```
4. Create **your team’s one branch** from `main` on the fork and push:
   ```bash
   git checkout main
   git pull upstream main
   git checkout -b team-<your-slug>
   git push -u origin team-<your-slug>
   ```
5. Open **pull requests** from your fork’s `team-<slug>` → **`main`** on the upstream repo when you want to land work (unless organizers say otherwise).
6. To sync new changes from the starter later:
   ```bash
   git fetch upstream
   git checkout main
   git merge upstream/main    # or rebase if your team prefers
   ```

## Pull request etiquette

- **Keep PRs small:** one vertical slice (e.g., “handle ‘pay’ intent in `app/bot.py`”) beats a giant refactor—even when the source branch is your team branch.
- **Title:** short imperative, e.g. “Add payment confirmation reply”.
- **Description (optional but helpful):** what changed + how you tested (WhatsApp message, `/health`, etc.).
- If the agent rewrote a lot by accident, **split the work** into smaller commits/PRs before merging.

## Secrets and local config

- **Never commit `.env`.** It is gitignored for a reason (API keys, tokens).
- **Do not paste secrets into shared chats or screenshots.** Use redacted logs when asking for help.

## Before merging (lightweight checklist)

- [ ] `http://127.0.0.1:8000/health` returns OK after your change (when relevant).
- [ ] You did not add secrets to the repo.
- [ ] If you touched inbound behavior: you tested with **Uvicorn + ngrok** and Kapso webhook configured (see `README.md`).

## When two people edit the same files

- **Communicate** in your team channel before large edits to `app/bot.py` or `app/services/kapso_client.py`.
- Prefer **merging `main` into your team branch** (or rebasing onto `main`) right before you push, so conflicts are fixed while the context is fresh.

## Organizers (optional GitHub settings)

If you want extra safety on `main`:

- Require pull requests (even if review is quick).
- Disable force-push to `main`.
- Use branch protection appropriate for your group size—don’t slow teams down unnecessarily.

Questions? Start with `README.md` and the Cursor rule `.cursor/rules/kapso-hackathon-setup.mdc`.

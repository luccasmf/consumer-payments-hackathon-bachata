# Contributing (hackathon workflow)

**This file is optional.** Use it if your team wants a shared playbook for Git + PRs. You can branch directly on the canonical repo or use a fork—both are valid (see below).

This repo is meant for **fast collaboration** while many people **vibe-code with Cursor Agent**. The goal is to ship a working WhatsApp demo without merge-conflict chaos.

## Default model: one repo, branches, small pull requests

We recommend **one shared repository** when everyone can push to the same repo (simplest for class / org hackathons).

- Each teammate works on a **short-lived branch**.
- Open **small pull requests** and merge to `main` **often** (multiple times per day is fine).
- **Pull `main` before you start** each coding session to reduce conflicts.

### Branch naming

Use a prefix so it’s obvious who owns the work:

- `team-<name>/<short-topic>` — e.g. `team-banana/fix-payment-reply`
- or `<your-name>/<short-topic>` — e.g. `alex/add-receipt-parser`

Keep topics **narrow** (one behavior / one flow) so PRs stay reviewable.

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
4. Create a branch, commit, and push to **your fork** (`origin`):
   ```bash
   git checkout -b team/my-feature
   git push -u origin team/my-feature
   ```
5. Open a **pull request** from your fork’s branch → **`main`** on the upstream repo (unless organizers say otherwise).
6. To sync new changes from the starter later:
   ```bash
   git fetch upstream
   git checkout main
   git merge upstream/main    # or rebase if your team prefers
   ```

## Pull request etiquette

- **Keep PRs small:** one vertical slice (e.g., “handle ‘pay’ intent in `app/bot.py`”) beats a giant refactor.
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
- Prefer **merging `main` into your branch** (or rebasing onto `main`) right before you push, so conflicts are fixed while the context is fresh.

## Organizers (optional GitHub settings)

If you want extra safety on `main`:

- Require pull requests (even if review is quick).
- Disable force-push to `main`.
- Use branch protection appropriate for your group size—don’t slow teams down unnecessarily.

Questions? Start with `README.md` and the Cursor rule `.cursor/rules/kapso-hackathon-setup.mdc`.

"""Playwright helpers to read Monito money-transfer compare pages."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import NamedTuple

from playwright.async_api import Page, async_playwright


def build_monito_compare_url(
    *,
    from_country: str = "us",
    to_country: str = "co",
    send_currency: str = "usd",
    receive_currency: str = "cop",
    send_amount: int | float = 100,
    locale: str = "en",
) -> str:
    """Build Monito compare URL: /{locale}/compare/transfer/{from}/{to}/{sendCcy}/{recvCcy}/{amount}."""
    fc = from_country.strip().lower()
    tc = to_country.strip().lower()
    sc = send_currency.strip().lower()
    rc = receive_currency.strip().lower()
    if len(fc) != 2 or len(tc) != 2:
        raise ValueError("from_country and to_country must be 2-letter ISO codes (e.g. us, mx)")
    if len(sc) != 3 or len(rc) != 3:
        raise ValueError("send_currency and receive_currency must be 3-letter codes (e.g. usd, mxn)")
    amt_f = float(send_amount)
    amt: int | float = int(amt_f) if amt_f == int(amt_f) else amt_f
    loc = locale.strip().lower()
    return (
        f"https://www.monito.com/{loc}/compare/transfer/"
        f"{fc}/{tc}/{sc}/{rc}/{amt}"
    )


def parse_monito_compare_url(url: str) -> tuple[str, str, str, str, float] | None:
    """Parse corridor from a monito compare URL, or return None if it does not match."""
    m = re.search(
        r"/compare/transfer/([a-z]{2})/([a-z]{2})/([a-z]{3})/([a-z]{3})/([\d.]+)",
        url,
        re.I,
    )
    if not m:
        return None
    return (
        m.group(1).lower(),
        m.group(2).lower(),
        m.group(3).lower(),
        m.group(4).lower(),
        float(m.group(5)),
    )


DEFAULT_URL = build_monito_compare_url()

SLUG_LABELS: dict[str, str] = {
    "remitly": "Remitly",
    "western-union": "Western Union",
    "moneygram-us": "MoneyGram",
    "moneygram": "MoneyGram",
    "wise-rm": "Wise",
    "wise": "Wise",
    "worldremit": "WorldRemit",
    "ria": "Ria",
    "paysend": "Paysend",
    "instarem": "Instarem",
    "xe-money-transfer": "XE Money Transfer",
    "xoom": "Xoom",
    "taptap-send": "TapTap Send",
    "taptap-send-us": "TapTap Send",
    "taptapsend_logo": "TapTap Send",
}


def label_for_slug(slug: str) -> str:
    base = re.sub(r"\.(png|svg)$", "", slug.lower(), flags=re.I)
    return SLUG_LABELS.get(base, SLUG_LABELS.get(slug.lower(), slug.replace("-", " ").title()))


class ProviderRow(NamedTuple):
    slug: str
    label: str
    receive_max: int


@dataclass(frozen=True)
class MonitoCompareResult:
    """Outcome of a single compare-page fetch."""

    url: str
    headless: bool
    from_country: str
    to_country: str
    send_currency: str
    receive_currency: str
    send_amount: float
    providers: tuple[ProviderRow, ...]
    timing_s: dict[str, float]
    receive_amount_regex_hits: int
    provider_row_count: int


def _wait_pattern(receive_currency: str) -> str:
    ccy = re.escape(receive_currency.strip().lower())
    return rf"\d{{1,3}}(?:,\d{{3}})+\s*{ccy}"


def _extract_pattern(receive_currency: str) -> str:
    ccy = re.escape(receive_currency.strip().lower())
    return rf"(\d{{1,3}}(?:,\d{{3}})+)\s*{ccy}"


async def dismiss_common_consent(page: Page) -> None:
    selectors = (
        'button:has-text("Accept")',
        'button:has-text("Agree")',
        'button:has-text("I agree")',
        '[aria-label="Accept"]',
    )
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=1500):
                await loc.click()
                await asyncio.sleep(0.4)
        except Exception:
            continue


async def wait_for_receive_quotes(
    page: Page,
    receive_currency: str,
    *,
    poll_s: float,
    timeout_s: float,
) -> tuple[float, int]:
    """Wait until compare rows exist (PSP logo in a list row), or body shows receive amounts."""
    pat = _wait_pattern(receive_currency)
    start = time.perf_counter()
    deadline = start + timeout_s
    last = 0
    while time.perf_counter() < deadline:
        state = await page.evaluate(
            """(pat) => {
              const t = document.body?.innerText || "";
              const re = new RegExp(pat, "gi");
              const m = t.match(re);
              const regexCount = m ? m.length : 0;
              const rowCount = [...document.querySelectorAll('li.relative')].filter(
                (li) => li.querySelector('img[src*="/psp/"]')
              ).length;
              return { regexCount, rowCount };
            }""",
            pat,
        )
        last = int(state["regexCount"])
        rows = int(state["rowCount"])
        # Require a real provider list row — body text can mention COP/MXN before the SPA renders.
        if rows >= 1:
            return time.perf_counter() - start, last
        await asyncio.sleep(poll_s)
    ccy_u = receive_currency.strip().upper()
    raise TimeoutError(
        f"No provider compare rows after {timeout_s}s "
        f"(regex_hits={last}, need li.relative with /psp/ logo)"
    )


async def scroll_until_provider_rows_stable(
    page: Page,
    *,
    pause_s: float,
    max_rounds: int,
) -> tuple[float, int]:
    start = time.perf_counter()
    prev = -1
    stable_rounds = 0
    last_count = 0
    for _ in range(max_rounds):
        last_count = await page.evaluate(
            r"""() => [...document.querySelectorAll('li.relative')].filter(
                (li) => li.querySelector('img[src*="/psp/"]')
            ).length"""
        )
        if last_count == prev:
            stable_rounds += 1
            if stable_rounds >= 2:
                break
        else:
            stable_rounds = 0
        prev = last_count
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(pause_s)
    return time.perf_counter() - start, last_count


async def extract_provider_best_receive(
    page: Page, receive_currency: str
) -> list[ProviderRow]:
    pat = _extract_pattern(receive_currency)
    raw = await page.evaluate(
        """(pat) => {
          function slugFromSrc(src) {
            const s0 = src || "";
            const i = s0.indexOf("/psp/");
            if (i < 0) return null;
            let s = s0.slice(i + 5).split("?")[0].split("#")[0];
            s = s.replace(/\\.svg.*$/i, "").replace(/\\.png.*$/i, "");
            return s || null;
          }
          function receiveValues(text) {
            const out = [];
            const re = new RegExp(pat, "gi");
            let m;
            while ((m = re.exec(text || ""))) {
              out.push(parseInt(m[1].replace(/,/g, ""), 10));
            }
            return out;
          }
          const bestBySlug = {};
          for (const img of document.querySelectorAll('img[src*="/psp/"]')) {
            const slug = slugFromSrc(img.getAttribute("src"));
            if (!slug) continue;
            const li = img.closest("li.relative");
            if (!li) continue;
            const vals = receiveValues(li.innerText);
            if (!vals.length) continue;
            const rowMax = Math.max(...vals);
            if (!(slug in bestBySlug) || rowMax > bestBySlug[slug]) {
              bestBySlug[slug] = rowMax;
            }
          }
          return Object.entries(bestBySlug).map(([slug, maxRecv]) => ({ slug, maxRecv }));
        }""",
        pat,
    )
    rows: list[ProviderRow] = []
    for item in raw:
        slug = str(item["slug"])
        amt = int(item["maxRecv"])
        rows.append(ProviderRow(slug=slug, label=label_for_slug(slug), receive_max=amt))
    rows.sort(key=lambda r: r.receive_max, reverse=True)
    return rows


async def fetch_monito_compare(
    url: str | None = None,
    *,
    from_country: str = "us",
    to_country: str = "co",
    send_currency: str = "usd",
    receive_currency: str = "cop",
    send_amount: int | float = 100,
    locale: str = "en",
    headless: bool = True,
    timeout_s: float = 120.0,
    poll_s: float = 0.5,
    scroll_pause_s: float = 0.8,
    scroll_max_rounds: int = 12,
) -> MonitoCompareResult:
    """Open Monito compare URL (built from corridor args if url is None)."""
    resolved_url = url or build_monito_compare_url(
        from_country=from_country,
        to_country=to_country,
        send_currency=send_currency,
        receive_currency=receive_currency,
        send_amount=send_amount,
        locale=locale,
    )
    parsed = parse_monito_compare_url(resolved_url)
    if parsed:
        fc, tc, sc, rc, amt = parsed
    else:
        fc = from_country.strip().lower()
        tc = to_country.strip().lower()
        sc = send_currency.strip().lower()
        rc = receive_currency.strip().lower()
        amt = float(send_amount)

    send_amt_f = float(amt)
    recv_ccy = rc
    send_ccy = sc

    t0 = time.perf_counter()
    timing: dict[str, float] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        t1 = time.perf_counter()
        await page.goto(resolved_url, wait_until="domcontentloaded", timeout=int(timeout_s * 1000))
        timing["goto_s"] = time.perf_counter() - t1

        await dismiss_common_consent(page)

        t2 = time.perf_counter()
        wait_elapsed, recv_hits = await wait_for_receive_quotes(
            page,
            recv_ccy,
            poll_s=poll_s,
            timeout_s=timeout_s,
        )
        timing["wait_for_quotes_s"] = wait_elapsed

        t3 = time.perf_counter()
        scroll_elapsed, row_count = await scroll_until_provider_rows_stable(
            page,
            pause_s=scroll_pause_s,
            max_rounds=scroll_max_rounds,
        )
        timing["scroll_until_stable_s"] = time.perf_counter() - t3

        t4 = time.perf_counter()
        providers = await extract_provider_best_receive(page, recv_ccy)
        timing["extract_s"] = time.perf_counter() - t4

        await browser.close()

    timing["total_s"] = time.perf_counter() - t0
    return MonitoCompareResult(
        url=resolved_url,
        headless=headless,
        from_country=fc,
        to_country=tc,
        send_currency=send_ccy,
        receive_currency=recv_ccy,
        send_amount=send_amt_f,
        providers=tuple(providers),
        timing_s=timing,
        receive_amount_regex_hits=recv_hits,
        provider_row_count=row_count,
    )

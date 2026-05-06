import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from app.schemas import MessageResponse, MonitoCompareRequest, SendTextRequest
from app.services.kapso_client import KapsoClient

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/send-text", response_model=MessageResponse)
async def send_text(req: SendTextRequest) -> MessageResponse:
    """Send a plain text message (useful for curl/Postman tests)."""
    try:
        client = KapsoClient()
        result = await client.send_whatsapp_message(req.to, req.text)
        mid = None
        if isinstance(result.get("messages"), list) and result["messages"]:
            mid = result["messages"][0].get("id")
        return MessageResponse(success=True, message_id=mid)
    except Exception as e:
        logger.exception("send_text failed")
        return MessageResponse(success=False, error=str(e))


@router.get("/kapso/account")
async def kapso_account() -> dict:
    """Call Kapso Platform API ``GET /platform/v1/integrations`` (confirms API key)."""
    try:
        client = KapsoClient()
        return await client.get_account_info()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except httpx.HTTPStatusError as e:
        detail = e.response.text or str(e)
        raise HTTPException(
            status_code=e.response.status_code,
            detail=detail[:4000],
        ) from e
    except httpx.HTTPError as e:
        logger.exception("kapso_account upstream error")
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/monito/compare")
async def monito_compare(req: MonitoCompareRequest) -> list[dict[str, Any]]:
    """Scrape Monito compare (Playwright) for US → ``country`` at ``amount``; returns provider rows only.

    This can take tens of seconds. Requires Chromium: ``playwright install chromium``.
    """
    from app.services.monito_playwright_service import MonitoPlaywrightService

    service = MonitoPlaywrightService()
    try:
        return await service.compare(
            req.country,
            req.amount,
            receive_currency=req.receive_currency,
            top=req.top,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except TimeoutError as e:
        logger.warning("monito_compare timeout: %s", e)
        raise HTTPException(
            status_code=504,
            detail="Monito compare timed out before results were ready.",
        ) from e
    except Exception as e:
        logger.exception("monito_compare failed")
        raise HTTPException(
            status_code=502,
            detail=str(e)[:4000],
        ) from e

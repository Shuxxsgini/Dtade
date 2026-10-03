"""Talks to the external notification provider (like your demo's notifications.py).

Four layers of protection:
  1. TIMEOUT  - never wait more than TIMEOUT_SECONDS for one attempt
  2. RETRY    - try up to MAX_ATTEMPTS times, waiting a bit longer each time
  3. BREAKER  - after repeated failures, stop calling the provider for a while
  4. FALLBACK - if it still fails, log it "to send later" and carry on; NEVER crash the caller
"""
import asyncio
import logging

import httpx

from app.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from app.core.config import settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 2              # max wait for ONE attempt
MAX_ATTEMPTS = 3                 # 1 try + 2 retries
RETRY_DELAY_SECONDS = 0.5        # wait 0.5s before retry 1, 1.0s before retry 2 (grows each time)

# ONE breaker for the whole app: it must remember failures ACROSS requests (same as your demo)
provider_breaker = CircuitBreaker(max_failures=3, reset_seconds=30)


async def send_to_provider(to: str, message: str) -> None:
    """ONE HTTP call to the provider. Raises on timeout, no connection, or an error status."""
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:     # the 2-second stopwatch
        response = await client.post(
            settings.notification_provider_url, json={"to": to, "message": message}
        )
        response.raise_for_status()                                       # 503 -> httpx.HTTPStatusError


async def send_with_retry(to: str, message: str) -> None:
    """Call send_to_provider up to MAX_ATTEMPTS times. Raises the last error if all fail."""
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):                            # attempt = 1, 2, 3
        try:
            await send_to_provider(to, message)
            return                                                        # success: stop trying
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:                            # 4xx = OUR request is wrong,
                raise                                                     # retrying won't fix it
            last_error = exc                                              # 5xx = provider problem, retry
        except httpx.TransportError as exc:                               # timeout or no connection
            last_error = exc

        logger.warning("Notification attempt %s/%s to %s failed (%s)",
                       attempt, MAX_ATTEMPTS, to, type(last_error).__name__)
        if attempt < MAX_ATTEMPTS:
            await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)            # 0.5s, then 1.0s ("backoff")

    raise last_error                                                      # all attempts failed


async def notify(to: str, message: str) -> bool:
    """The ONLY function the rest of the app calls. Never raises.

    Returns True if sent, False if not (logged so it can be sent later).
    """
    try:
        await provider_breaker.call(send_with_retry, to, message)        # breaker wraps all the retries
        logger.warning("Notification SENT to %s", to)                      # (warning level so it shows in logs for now)
        return True
    except CircuitOpenError:
        logger.warning("Notification to %s NOT SENT: provider breaker is open, keep for later", to)
        return False
    except Exception as exc:                                              # FALLBACK: anything else
        logger.warning("Notification to %s NOT SENT, keep for later (%s)", to, type(exc).__name__)
        return False

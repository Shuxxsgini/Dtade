"""Everything about logs: one log format, and a sticker (request id) on every request."""
import logging
import time
import uuid
from contextvars import ContextVar

from fastapi import Request
from fastapi.responses import JSONResponse

# A sticky note that belongs to the CURRENT request only. Every log line reads it.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

logger = logging.getLogger("app.requests")


class RequestIdFilter(logging.Filter):
    """Just before a log line is printed, stick the current request id onto it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True                                    # True = yes, print this line


def setup_logging() -> None:
    """One format for the whole app: time | level | request id | who wrote it | message."""
    handler = logging.StreamHandler()                  # print to the terminal (docker compose logs)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | req=%(request_id)s | %(name)s | %(message)s"
    ))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)   # force = replace any old setup


async def log_requests(request: Request, call_next):
    """Middleware: wraps EVERY request, like a receptionist with a stopwatch."""
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:8]  # reuse the caller's id, or make one
    request_id_var.set(request_id)                     # write the sticker for this request
    start = time.perf_counter()                        # start the stopwatch

    try:
        response = await call_next(request)            # let the real endpoint do its work
    except Exception:                                  # a bug nobody expected: never show a raw crash
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)  # full traceback in logs
        response = JSONResponse(
            status_code=500,
            content={"detail": "Internal server error.", "request_id": request_id},
        )

    ms = (time.perf_counter() - start) * 1000          # stop the stopwatch
    logger.info("%s %s -> %s (%.0f ms)", request.method, request.url.path, response.status_code, ms)
    response.headers["X-Request-ID"] = request_id      # hand the sticker back to the caller
    return response

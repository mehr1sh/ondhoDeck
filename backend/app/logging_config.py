"""Structured, privacy-preserving logging: no request bodies, tokens, document text or amounts."""
from __future__ import annotations

import logging
import re
import sys

from .config import get_settings

_SECRET_PATTERNS = [re.compile(p) for p in (r"Bearer\s+[A-Za-z0-9._-]+", r"sk-[A-Za-z0-9_-]{8,}",
                                            r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")]


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for p in _SECRET_PATTERNS:
            msg = p.sub("[REDACTED]", msg)
        record.msg, record.args = msg, ()
        return True


_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(get_settings().log_level.upper())
    for noisy in ("httpx", "httpcore", "pymupdf"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True

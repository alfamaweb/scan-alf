from __future__ import annotations

MAX_PAGES = 150
MAX_DEPTH = 6
MAX_RUNTIME_SECONDS = 120
PER_PAGE_TIMEOUT_SECONDS = 20
MAX_LINK_CHECKS = 400
USER_AGENT = "SimpleSiteAuditBot/1.0"


SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}
SEVERITY_PENALTY = {"critical": 35, "high": 20, "medium": 10, "low": 4}

SECTION_KEYS = [
    "overall",
    "seo",
    "a11y",
    "content",
    "performance",
    "erros_criticos",
]

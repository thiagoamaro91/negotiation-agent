"""One scrubber for everything that leaves the key machine or is shown on a page (team relay, brain intake, desks).

The game's credential shapes (kit/README.md, agent/broker.py, agent/runlog.py): team keys `tk-XXXX-XXXX`, broker keys
`bk_...`, admin keys `adm_...`; the dash and underscore variants of each prefix are covered too, so a key in a
decision's free text is redacted whatever shape it takes. Any field whose name mentions a key, token or secret is
dropped at any depth.
"""
from __future__ import annotations

import re

SECRET = re.compile(r"\b(?:tk|bk|sk|adm)[-_][A-Za-z0-9_-]{4,}")
FIELD_WORDS = ("key", "token", "secret")


def secret_field(name) -> bool:
    return any(w in str(name).lower() for w in FIELD_WORDS)


def scrub(x, limit: int | None = None):
    """Drop key/token/secret-named fields at any depth, redact credential-shaped strings, cut long text to `limit`."""
    if isinstance(x, dict):
        return {k: scrub(v, limit) for k, v in x.items() if not secret_field(k)}
    if isinstance(x, list):
        return [scrub(v, limit) for v in x]
    if isinstance(x, str):
        x = SECRET.sub("[redacted]", x)
        return x[:limit] if limit else x
    return x

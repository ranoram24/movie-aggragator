"""The shared secret guarding every write path on this server.

One token, checked the same way everywhere, so there is a single answer to
"what can an anonymous caller make this server do".

Read endpoints stay open -- the whole point of the app is public showtimes --
but anything that writes to the database or spends the machine's time is
behind this.
"""

import os
import secrets

from fastapi import Header, HTTPException

# Set as a platform secret. With nothing configured every guarded endpoint
# refuses rather than defaulting to open: a write path that falls back to
# unauthenticated on a misconfigured deploy is worse than one that is simply
# down, because nothing about it looks broken.
TOKEN = os.getenv("INGEST_TOKEN", "")


def check_token(provided: str | None) -> None:
    if not TOKEN:
        raise HTTPException(503, "This server has no INGEST_TOKEN configured.")
    # Constant-time. A plain == returns faster the earlier it finds a
    # mismatching byte, which leaks the secret one character at a time to
    # anyone willing to measure enough requests.
    if not provided or not secrets.compare_digest(provided, TOKEN):
        raise HTTPException(401, "Invalid or missing token.")


def require_token(x_ingest_token: str | None = Header(None)) -> None:
    """FastAPI dependency form, for guarding a route with `dependencies=`."""
    check_token(x_ingest_token)

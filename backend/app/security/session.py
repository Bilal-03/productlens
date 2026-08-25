from __future__ import annotations

import hashlib
import hmac


def hash_session(session_id: str, secret: str) -> str:
    return hmac.new(secret.encode(), session_id.encode(), hashlib.sha256).hexdigest()


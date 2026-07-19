"""Google Identity Services sign-in: ID-token verification.

Uses the ID-token credential flow only: the browser's Google button hands us a
signed ID token, and we verify it server-side with Google's official
google-auth library. No client secret is involved anywhere — the Client ID is
public by design (it ships to every browser), so the default lives in code and
STARSHOT_GOOGLE_CLIENT_ID can override it.
"""

from __future__ import annotations

import os

GOOGLE_CLIENT_ID = os.environ.get(
    "STARSHOT_GOOGLE_CLIENT_ID",
    "767497052681-as1k10s8i67r1p498i0l8thv4eht0qft.apps.googleusercontent.com",
)

_GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


def verify_google_credential(credential: str) -> dict:
    """Verify a Google ID token and return its claims.

    google-auth checks the signature (against Google's published certs),
    expiration, and that the audience matches GOOGLE_CLIENT_ID; the issuer is
    checked both by the library and belt-and-braces here. Raises ValueError
    for any invalid token.
    """
    # Imported lazily so tests that stub this function never need google-auth
    # on the import path.
    from google.auth.exceptions import GoogleAuthError
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    try:
        claims = google_id_token.verify_oauth2_token(
            credential, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except GoogleAuthError as exc:  # library-raised issuer mismatch
        raise ValueError(str(exc)) from exc
    if claims.get("iss") not in _GOOGLE_ISSUERS:
        raise ValueError(f"Unexpected issuer: {claims.get('iss')!r}")
    if not claims.get("sub"):
        raise ValueError("Token is missing the sub claim.")
    return claims

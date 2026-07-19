"""Microsoft identity platform sign-in: ID-token verification.

Uses the ID-token flow only: MSAL.js in the browser hands us a signed ID
token, and we verify it server-side against Microsoft's published JWKS keys.
No client secret is involved anywhere — the Application (client) ID is public
by design (it ships to every browser), so the default lives in code and
STARSHOT_MICROSOFT_CLIENT_ID can override it.
"""

from __future__ import annotations

import os

MICROSOFT_CLIENT_ID = os.environ.get(
    "STARSHOT_MICROSOFT_CLIENT_ID",
    "8020ee54-185e-476a-9d7a-74c3d47a7a8c",
)

# The /common authority accepts any Microsoft account, so tokens are issued by
# the user's home tenant: the issuer embeds the tenant id (tid claim).
_MICROSOFT_JWKS_URI = "https://login.microsoftonline.com/common/discovery/v2.0/keys"
_ISSUER_TEMPLATE = "https://login.microsoftonline.com/{tid}/v2.0"

_jwks_client = None


def verify_microsoft_credential(credential: str) -> dict:
    """Verify a Microsoft ID token and return its claims.

    PyJWT checks the signature (against Microsoft's published JWKS),
    expiration, and that the audience matches MICROSOFT_CLIENT_ID; the issuer
    must be the v2.0 endpoint of the token's own tenant. Raises ValueError
    for any invalid token.
    """
    # Imported lazily so tests that stub this function never need PyJWT on
    # the import path.
    import jwt

    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(_MICROSOFT_JWKS_URI)

    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(credential)
        claims = jwt.decode(
            credential,
            signing_key.key,
            algorithms=["RS256"],
            audience=MICROSOFT_CLIENT_ID,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise ValueError(str(exc)) from exc
    tid = claims.get("tid")
    if not tid or claims.get("iss") != _ISSUER_TEMPLATE.format(tid=tid):
        raise ValueError(f"Unexpected issuer: {claims.get('iss')!r}")
    if not claims.get("sub"):
        raise ValueError("Token is missing the sub claim.")
    return claims

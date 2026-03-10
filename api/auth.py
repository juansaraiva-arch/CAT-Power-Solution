"""
CAT Power Solution — Entra ID Authentication
=============================================
JWT validation for Microsoft Entra ID (Azure AD) tokens.
Supports role-based access via Security Groups.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import httpx
import jwt                          # PyJWT>=2.8.0
from functools import lru_cache
from api.config import get_settings

security = HTTPBearer(auto_error=False)


class AuthenticatedUser(BaseModel):
    email: str
    name: str
    groups: list[str] = []
    role: str = "demo"              # demo | full | admin


@lru_cache(maxsize=1)
def get_entra_public_keys(tenant_id: str) -> dict:
    """
    Fetch public keys from Entra ID JWKS endpoint.
    Cached — refreshed on app restart.
    """
    url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    response = httpx.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


def validate_token(token: str, settings) -> AuthenticatedUser:
    """
    Validate JWT token and extract user info.
    Raises HTTPException if token is invalid or expired.
    """
    try:
        keys = get_entra_public_keys(settings.entra_tenant_id)
        header = jwt.get_unverified_header(token)
        key = next(
            (k for k in keys["keys"] if k["kid"] == header["kid"]),
            None
        )
        if not key:
            raise HTTPException(status_code=401, detail="Invalid token key")

        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=f"api://{settings.entra_app_client_id}",
            issuer=f"https://login.microsoftonline.com/{settings.entra_tenant_id}/v2.0",
        )

        groups = payload.get("groups", [])

        # Resolver rol por grupo (orden: admin > full > demo)
        if settings.sg_admin in groups:
            role = "admin"
        elif settings.sg_full in groups:
            role = "full"
        elif settings.sg_demo in groups:
            role = "demo"
        else:
            raise HTTPException(
                status_code=403,
                detail="User does not belong to any CAT Power Solution group. "
                       "Contact francisco.saraiva@cat.com for access."
            )

        return AuthenticatedUser(
            email=payload.get("preferred_username", payload.get("email", "")),
            name=payload.get("name", ""),
            groups=groups,
            role=role,
        )

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    settings=Depends(get_settings),
) -> AuthenticatedUser:
    """
    FastAPI dependency. Use in route handlers that require authentication.
    If require_auth=False in settings, returns a mock user for local dev.
    """
    if not settings.require_auth:
        return AuthenticatedUser(
            email="dev@caterpillar.com",
            name="Local Developer",
            role="admin",
        )

    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return validate_token(credentials.credentials, settings)


def require_role(minimum_role: str):
    """
    Dependency factory. Use to restrict endpoints by role.

    Usage:
        @router.post("/full")
        def endpoint(user: AuthenticatedUser = Depends(require_role("full"))):
            ...
    """
    role_hierarchy = {"demo": 0, "full": 1, "admin": 2}
    required_level = role_hierarchy.get(minimum_role, 0)

    async def _check_role(user: AuthenticatedUser = Depends(get_current_user)):
        user_level = role_hierarchy.get(user.role, 0)
        if user_level < required_level:
            raise HTTPException(
                status_code=403,
                detail=f"This endpoint requires '{minimum_role}' access or higher. "
                       f"Your current role: '{user.role}'."
            )
        return user

    return _check_role

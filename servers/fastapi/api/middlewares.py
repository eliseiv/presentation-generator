import hmac

from fastapi import Request
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from utils.get_env import get_can_change_keys_env, get_service_api_key_env
from utils.user_config import update_env_with_user_config


class UserConfigEnvUpdateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if get_can_change_keys_env() != "false":
            update_env_with_user_config()
        return await call_next(request)


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

# Paths that third parties POST to. They authenticate via their own signed
# payloads / HMAC, not via our SERVICE_API_KEY, so the global middleware
# must let them through unconditionally — the handlers verify the
# signature themselves.
_SERVICE_API_KEY_EXEMPT_PATHS = {
    "/api/v1/billing/adapty/webhook",
}


class ServiceApiKeyMiddleware(BaseHTTPMiddleware):
    def _requires_auth(self, path: str) -> bool:
        if path in _SERVICE_API_KEY_EXEMPT_PATHS:
            return False
        if path.startswith("/api/"):
            return True
        if path.startswith("/app_data/"):
            return True
        return False

    def _extract_api_key(self, request: Request) -> str | None:
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return api_key.strip()

        auth_header = request.headers.get("Authorization", "")
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() == "bearer" and token:
            return token.strip()

        return None

    def _is_internal_asset_request(self, request: Request) -> bool:
        """
        Bypass auth for loopback-originated requests on /app_data/* and /static/*.

        Headless puppeteer renders the slide deck from inside the container and
        pulls the slide images via /app_data/images/<uuid>.png — those image
        requests cannot carry the service API key. They reach FastAPI through
        the container's internal nginx, which always rewrites X-Real-IP and
        X-Forwarded-For. External clients always traverse the same nginx, so
        the only way to tell the two apart is by inspecting the forwarded
        client IP itself: loopback ⇒ originated inside the container,
        otherwise ⇒ a real external request that must authenticate.
        """
        path = request.url.path
        if not (path.startswith("/app_data/") or path.startswith("/static/")):
            return False

        client_host = request.client.host if request.client else None
        if client_host not in _LOOPBACK_HOSTS:
            return False

        # Inspect every forwarded-IP hop: if any hop is non-loopback, the
        # original client is external and must authenticate.
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        for hop in forwarded_for.split(","):
            hop_ip = hop.strip().split("%", 1)[0]
            if hop_ip and hop_ip not in _LOOPBACK_HOSTS:
                return False

        real_ip = (request.headers.get("X-Real-IP") or "").strip()
        if real_ip and real_ip not in _LOOPBACK_HOSTS:
            return False

        return True

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if (
            request.method == "OPTIONS"
            or not self._requires_auth(path)
            or self._is_internal_asset_request(request)
        ):
            return await call_next(request)

        configured_api_key = (get_service_api_key_env() or "").strip()
        if not configured_api_key:
            return JSONResponse(
                status_code=500,
                content={"detail": "SERVICE_API_KEY is not configured"},
            )

        provided_api_key = self._extract_api_key(request)
        if not provided_api_key or not hmac.compare_digest(
            provided_api_key, configured_api_key
        ):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        request.state.service_api_key_authenticated = True
        return await call_next(request)


SessionAuthMiddleware = ServiceApiKeyMiddleware

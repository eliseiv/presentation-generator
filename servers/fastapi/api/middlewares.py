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


class ServiceApiKeyMiddleware(BaseHTTPMiddleware):
    def _requires_auth(self, path: str) -> bool:
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

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if (
            request.method == "OPTIONS"
            or not self._requires_auth(path)
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

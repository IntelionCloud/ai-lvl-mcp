"""HTTP-клиент к sync-api: login, refresh, авто-обновление access-токена."""
from __future__ import annotations

import time

import httpx


class AuthError(Exception):
    pass


class AiLvlClient:
    """Держит refresh-токен, сам минтит/обновляет access JWT, ходит на /api/v1/me/*."""

    def __init__(self, host: str, email: str, refresh_token: str):
        self.host = host.rstrip("/")
        self.email = email
        self._refresh_token = refresh_token
        self._access: str | None = None
        self._access_exp = 0.0

    # ── auth ──────────────────────────────────────────────────────────────────
    @classmethod
    def login(cls, host: str, email: str, password: str) -> "AiLvlClient":
        host = host.rstrip("/")
        r = httpx.post(f"{host}/api/v1/auth/login",
                       json={"email": email, "password": password}, timeout=30.0)
        if r.status_code == 401:
            raise AuthError("неверный email или пароль")
        if r.status_code == 403:
            raise AuthError("этого email нет в employees.yaml — обратитесь к админу ai-lvl")
        if r.status_code != 200:
            raise AuthError(f"login HTTP {r.status_code}: {r.text[:200]}")
        j = r.json()
        c = cls(host, email, j["refresh_token"])
        c._access = j["access_token"]
        c._access_exp = time.time() + j.get("expires_in", 3600)
        return c

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    def _refresh_access(self) -> None:
        r = httpx.post(f"{self.host}/api/v1/auth/refresh",
                       json={"refresh_token": self._refresh_token}, timeout=30.0)
        if r.status_code != 200:
            raise AuthError("refresh-токен недействителен/отозван — выполните `ai-lvl-mcp login`")
        j = r.json()
        self._access = j["access_token"]
        self._access_exp = time.time() + j.get("expires_in", 3600)

    def _ensure_access(self) -> None:
        if self._access and time.time() < self._access_exp - 60:
            return
        self._refresh_access()

    # ── requests ────────────────────────────────────────────────────────────
    def get(self, path: str, params: dict | None = None) -> dict:
        self._ensure_access()
        headers = {"Authorization": f"Bearer {self._access}"}
        r = httpx.get(f"{self.host}{path}", params=params or {}, headers=headers, timeout=60.0)
        if r.status_code == 401:  # access протух/отозван — один форс-refresh и повтор
            self._access = None
            self._ensure_access()
            r = httpx.get(f"{self.host}{path}", params=params or {},
                          headers={"Authorization": f"Bearer {self._access}"}, timeout=60.0)
        if r.status_code == 403:
            return {"error": "forbidden", "detail": r.json().get("detail") if r.headers.get(
                "content-type", "").startswith("application/json") else r.text[:200]}
        r.raise_for_status()
        return r.json()

    def post_json(self, path: str, body: dict, timeout: float = 300.0) -> dict:
        """POST JSON на sync-api с тем же 401-refresh-retry, что и get()."""
        self._ensure_access()
        headers = {"Authorization": f"Bearer {self._access}"}
        r = httpx.post(f"{self.host}{path}", json=body, headers=headers, timeout=timeout)
        if r.status_code == 401:  # access протух/отозван — один форс-refresh и повтор
            self._access = None
            self._ensure_access()
            r = httpx.post(f"{self.host}{path}", json=body,
                           headers={"Authorization": f"Bearer {self._access}"}, timeout=timeout)
        if r.status_code == 403:
            return {"error": "forbidden", "detail": r.json().get("detail") if r.headers.get(
                "content-type", "").startswith("application/json") else r.text[:200]}
        r.raise_for_status()
        return r.json()

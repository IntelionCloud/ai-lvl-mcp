"""Конфиг + хранение refresh-токена.

- ~/.ai-lvl/mcp.json — host + email (не секрет; JSON, чтобы не тянуть TOML-парсер и работать на py3.10+).
- refresh-токен — в OS-keychain (keyring). Если бэкенда keyring нет (часть Linux-десктопов,
  headless) — fallback в ~/.ai-lvl/refresh-<hash>.token с правами 0600 (менее безопасно,
  предупреждаем). Access-токен на диск НЕ пишем никогда — он живёт в памяти процесса.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("AI_LVL_CONFIG_DIR", Path.home() / ".ai-lvl"))
CONFIG_FILE = CONFIG_DIR / "mcp.json"
KEYRING_SERVICE = "ai-lvl-mcp"
DEFAULT_HOST = "https://ai-lvl.intelion.cloud"


def load_config() -> dict:
    """{host, email}. Env AI_LVL_HOST/AI_LVL_EMAIL переопределяют файл."""
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
        except Exception:
            data = {}
    host = os.environ.get("AI_LVL_HOST") or data.get("host") or DEFAULT_HOST
    email = os.environ.get("AI_LVL_EMAIL") or data.get("email")
    return {"host": host.rstrip("/"), "email": email}


def save_config(host: str, email: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({"host": host.rstrip("/"), "email": email}, ensure_ascii=False))
    CONFIG_FILE.chmod(0o600)


def _token_file(email: str) -> Path:
    h = hashlib.sha256(email.encode()).hexdigest()[:16]
    return CONFIG_DIR / f"refresh-{h}.token"


def get_refresh_token(email: str) -> str | None:
    try:
        import keyring
        tok = keyring.get_password(KEYRING_SERVICE, email)
        if tok:
            return tok
    except Exception:
        pass
    f = _token_file(email)
    return f.read_text().strip() if f.exists() else None


def set_refresh_token(email: str, token: str) -> str:
    """Возвращает 'keyring' или 'file' — куда лёг токен (для сообщения пользователю)."""
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, email, token)
        return "keyring"
    except Exception:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        f = _token_file(email)
        f.write_text(token)
        f.chmod(0o600)
        return "file"


def clear_refresh_token(email: str) -> None:
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, email)
    except Exception:
        pass
    f = _token_file(email)
    if f.exists():
        f.unlink()

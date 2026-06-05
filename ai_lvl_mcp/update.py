"""Автообновление клиента при старте `serve`.

Сервер отдаёт в `/api/v1/me → client` свою `latest_version` / `min_supported_version`.
При запуске MCP-сервера (до начала stdio-протокола) клиент сравнивает свою версию и,
если устарел, сам себя переустанавливает (pipx / uv tool / pip) и перезапускается
через `os.execv`. Всё — best-effort: при любой ошибке продолжаем на текущей версии,
чтобы не блокировать ии-агента. Жёсткий стоп только ниже `min_supported_version`.

ВАЖНО: всё пишем в stderr, вывод апгрейда — capture'им. stdout зарезервирован под
MCP JSON-RPC (любой мусор в stdout сломал бы протокол). execv сохраняет fd 0/1/2,
поэтому stdio-канал к Claude переживает перезапуск.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

from . import __version__
from .client import AiLvlClient, AuthError
from .config import get_refresh_token, load_config

_GUARD_ENV = "AI_LVL_MCP_SELF_UPDATED"      # маркер «уже пробовали в этой цепочке exec»
_DISABLE_VALUES = {"0", "false", "no", "off"}
_GIT_SPEC = "git+https://github.com/IntelionCloud/ai-lvl-mcp.git"


def _vtuple(s: str) -> tuple[int, ...]:
    """'0.4.0' → (0,4,0). Нецифровые суффиксы ('1.2.0rc1') обрезаются по компоненте."""
    out = []
    for part in (s or "0").split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits or 0))
    return tuple(out)


def _server_versions() -> tuple[str | None, str | None]:
    """(latest, min) из /api/v1/me.client — best-effort, при ошибке (None, None)."""
    cfg = load_config()
    if not cfg["email"]:
        return None, None
    token = get_refresh_token(cfg["email"])
    if not token:
        return None, None
    try:
        info = (AiLvlClient(cfg["host"], cfg["email"], token).get("/api/v1/me") or {}).get("client") or {}
    except (AuthError, Exception):  # noqa: BLE001 — сеть/авторизация недоступны → молча скип
        return None, None
    return info.get("latest_version"), info.get("min_supported_version")


def _disk_version() -> str | None:
    """Версия пакета на диске (после апгрейда наш in-memory __version__ устарел)."""
    try:
        r = subprocess.run(
            [sys.executable, "-c",
             "import importlib.metadata as m; print(m.version('ai-lvl-mcp'))"],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    return None


def _run_upgrade() -> bool:
    """Переустановить пакет последней версией. True — если команда апгрейда отработала.

    Порядок кандидатов покрывает основные способы установки: pipx, uv tool, pip-в-venv.
    Неподходящий менеджер вернёт ненулевой код → пробуем следующий.
    """
    candidates: list[list[str]] = []
    if shutil.which("pipx"):
        candidates.append(["pipx", "upgrade", "ai-lvl-mcp"])
    if shutil.which("uv"):
        candidates.append(["uv", "tool", "upgrade", "ai-lvl-mcp"])
    candidates.append([sys.executable, "-m", "pip", "install", "-U", _GIT_SPEC])
    for cmd in candidates:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        except Exception as e:  # noqa: BLE001
            print(f"ℹ ai-lvl-mcp: {cmd[0]} не сработал: {e}", file=sys.stderr)
            continue
        if r.returncode == 0:
            return True
        print(f"ℹ ai-lvl-mcp: {' '.join(cmd[:2])} → код {r.returncode}: "
              f"{(r.stderr or r.stdout or '').strip()[:200]}", file=sys.stderr)
    return False


def _enforce_min(minv: str | None) -> None:
    """Backstop: ниже min_supported и обновиться не вышло → не стартуем (форсим ручной апгрейд)."""
    if minv and _vtuple(__version__) < _vtuple(minv):
        print(f"⛔ ai-lvl-mcp {__version__} ниже минимально поддерживаемой {minv} и "
              f"автообновление не удалось. Обновитесь вручную: pipx upgrade ai-lvl-mcp",
              file=sys.stderr)
        sys.exit(1)


def maybe_self_update() -> None:
    """Точка входа: вызывается из server.run() ДО mcp.run()."""
    disabled = os.environ.get("AI_LVL_MCP_AUTO_UPDATE", "1").lower() in _DISABLE_VALUES
    latest, minv = _server_versions()
    cur = _vtuple(__version__)

    # Уже перезапускались в этой цепочке — не зацикливаемся; только enforce min.
    if os.environ.get(_GUARD_ENV) == "1":
        if latest and cur < _vtuple(latest):
            print(f"ℹ ai-lvl-mcp: после автообновления версия {__version__}, "
                  f"сервер ждёт {latest}. Продолжаю на текущей.", file=sys.stderr)
        _enforce_min(minv)
        return

    if disabled:
        # Автообновление выключено сотрудником — мягкий нудж + backstop по min.
        if latest and cur < _vtuple(latest):
            print(f"ℹ ai-lvl-mcp: установлена {__version__}, доступна {latest} "
                  f"(автообновление выключено). Обновление: pipx upgrade ai-lvl-mcp", file=sys.stderr)
        _enforce_min(minv)
        return

    if latest and cur < _vtuple(latest):
        print(f"ℹ ai-lvl-mcp: обновляюсь {__version__} → {latest}…", file=sys.stderr)
        if _run_upgrade():
            new = _disk_version()
            if new and _vtuple(new) > cur:
                print(f"✓ ai-lvl-mcp обновлён {__version__} → {new}, перезапуск.", file=sys.stderr)
                os.environ[_GUARD_ENV] = "1"
                os.execv(sys.executable, [sys.executable, "-m", "ai_lvl_mcp", "serve"])
            else:
                print(f"ℹ ai-lvl-mcp: апгрейд выполнен, версия осталась "
                      f"{new or __version__}; продолжаю.", file=sys.stderr)
        else:
            print("⚠ ai-lvl-mcp: автообновление не удалось — `pipx upgrade ai-lvl-mcp`.",
                  file=sys.stderr)

    _enforce_min(minv)

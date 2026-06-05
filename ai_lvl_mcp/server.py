"""FastMCP stdio-сервер. Инструменты проксируют на sync-api /api/v1/me/* под JWT сотрудника.

Все инструменты read-only и автоматически ограничены доступными сотруднику spaces
(ACL считается на стороне sync-api). Если сотрудник не залогинен — инструмент вернёт
понятную ошибку с подсказкой `ai-lvl-mcp login`.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import sys
import time

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import __version__
from .client import AiLvlClient, AuthError
from .config import get_refresh_token, load_config

mcp = FastMCP(name="ai-lvl")

_client: AiLvlClient | None = None


def _get_client() -> AiLvlClient:
    global _client
    if _client is not None:
        return _client
    cfg = load_config()
    if not cfg["email"]:
        raise AuthError("не задан email — выполните `ai-lvl-mcp login` (или задайте AI_LVL_EMAIL)")
    token = get_refresh_token(cfg["email"])
    if not token:
        raise AuthError("нет сохранённого токена — выполните `ai-lvl-mcp login`")
    _client = AiLvlClient(cfg["host"], cfg["email"], token)
    return _client


def _call(path: str, params: dict | None = None) -> str:
    try:
        return json.dumps(_get_client().get(path, params), ensure_ascii=False, indent=2)
    except AuthError as e:
        return json.dumps({"error": "not_authenticated", "hint": str(e)}, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001 — наружу отдаём короткий текст, не стектрейс
        return json.dumps({"error": "request_failed", "detail": str(e)[:300]}, ensure_ascii=False)


def _post(path: str, body: dict, timeout: float = 300.0) -> dict:
    """POST + единый error-shape (как _call, но возвращает dict для постобработки)."""
    try:
        return _get_client().post_json(path, body, timeout=timeout)
    except AuthError as e:
        return {"error": "not_authenticated", "hint": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"error": "request_failed", "detail": str(e)[:300]}


@mcp.tool()
def whoami() -> str:
    """Кто я в ai-lvl и какие spaces мне доступны (slug, sensitivity, можно ли писать)."""
    return _call("/api/v1/me")


@mcp.tool()
def list_spaces() -> str:
    """Список доступных мне spaces с уровнем доступа (то же, что whoami → spaces)."""
    return _call("/api/v1/me")


@mcp.tool()
def search(
    query: str = Field(description="Поисковый запрос (русский/английский)."),
    top: int = Field(10, description="Сколько результатов вернуть (1-50)."),
    space: str | None = Field(None, description="Опц.: ограничить одним slug (без префикса space-)."),
) -> str:
    """Hybrid-поиск (BM25 + semantic + rerank) по доступным мне spaces."""
    params: dict = {"q": query, "top": top}
    if space:
        params["space"] = space
    return _call("/api/v1/me/search", params)


@mcp.tool()
def get_node(
    node_id: str = Field(description="ID узла в формате 'slug/note-name'."),
) -> str:
    """Полная заметка: frontmatter, тело, edges (wikilinks). Только из доступных мне spaces."""
    return _call("/api/v1/me/node", {"node_id": node_id})


@mcp.tool()
def recent_changes(
    since: str = Field(description="ISO-дата/время, от которого показывать изменения."),
    space: str | None = Field(None, description="Опц.: один slug."),
    limit: int = Field(20, description="Максимум элементов (1-100)."),
) -> str:
    """Что нового в моих spaces с момента `since` (для дайджеста «что изменилось»)."""
    params: dict = {"since": since, "limit": limit}
    if space:
        params["space"] = space
    return _call("/api/v1/me/recent", params)


@mcp.tool()
def similar(
    node_id: str = Field(description="ID узла 'slug/note-name'."),
    top: int = Field(10, description="Сколько похожих вернуть (1-50)."),
) -> str:
    """Семантически похожие заметки из доступных мне spaces."""
    return _call("/api/v1/me/similar", {"node_id": node_id, "top": top})


# ── Media-инструменты (FLUX image-gen + Parakeet ASR через AI API RUS) ────────
# Доступны роли author и приватному тиру; бесплатно (биллинг на сервисный аккаунт).
# Ключ AI API живёт на сервере — клиент шлёт промпт/аудио под своим JWT.

@mcp.tool()
def generate_image(
    prompt: str = Field(description="Текстовый промпт для генерации изображения (любой язык)."),
    output_path: str | None = Field(
        None, description="Куда сохранить PNG. По умолчанию — в текущую папку, имя по таймстемпу."),
    size: str = Field("1024x1024", description="Размер, напр. '1024x1024' или '512x512'."),
    n: int = Field(1, description="Сколько изображений сгенерировать (1-4)."),
) -> str:
    """Сгенерировать изображение по промпту (FLUX.1-schnell). Сохраняет PNG локально и
    возвращает путь(и). Бесплатно для авторов и приватного доступа."""
    n = max(1, min(int(n), 4))
    res = _post("/api/v1/me/generate-image", {"prompt": prompt, "size": size, "n": n}, timeout=240.0)
    if "error" in res:
        return json.dumps(res, ensure_ascii=False)
    data = res.get("data") or []
    if not data:
        return json.dumps({"error": "no_image", "detail": str(res)[:300]}, ensure_ascii=False)
    base = os.path.expanduser(output_path) if output_path else os.path.join(
        os.getcwd(), f"ai-lvl-image-{int(time.time())}.png")
    root, ext = os.path.splitext(base)
    ext = ext or ".png"
    saved = []
    for i, item in enumerate(data):
        b64 = item.get("b64_json")
        if not b64:
            continue
        path = base if len(data) == 1 else f"{root}-{i+1}{ext}"
        try:
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64))
            saved.append(os.path.abspath(path))
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": "write_failed", "detail": str(e)[:200]}, ensure_ascii=False)
    return json.dumps({"ok": True, "model": "flux.1-schnell", "saved": saved,
                       "count": len(saved)}, ensure_ascii=False, indent=2)


@mcp.tool()
def transcribe_audio(
    file_path: str = Field(description="Путь к локальному аудиофайлу (wav/mp3/m4a/flac/ogg…)."),
    language: str | None = Field(None, description="Опц. код языка-подсказки, напр. 'ru' или 'en'."),
) -> str:
    """Распознать речь из аудиофайла (Parakeet, RU/EN и ещё 23 языка). Возвращает текст.
    Бесплатно для авторов и приватного доступа."""
    path = os.path.expanduser(file_path)
    if not os.path.isfile(path):
        return json.dumps({"error": "file_not_found", "detail": path}, ensure_ascii=False)
    try:
        with open(path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("ascii")
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": "read_failed", "detail": str(e)[:200]}, ensure_ascii=False)
    ctype, _ = mimetypes.guess_type(path)
    body = {"audio_b64": audio_b64, "filename": os.path.basename(path),
            "content_type": ctype or "application/octet-stream"}
    if language:
        body["language"] = language
    res = _post("/api/v1/me/transcribe", body, timeout=300.0)
    return json.dumps(res, ensure_ascii=False, indent=2)


def _vtuple(s: str) -> tuple[int, ...]:
    """'0.2.0' → (0,2,0). Нецифровые суффиксы ('1.2.0rc1') обрезаются по компоненте."""
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


def _check_version() -> None:
    """Server-driven version-nudge: сравнить свою версию с latest/min из /api/v1/me.

    Best-effort: при сетевой ошибке/не-залогинен — молча пропускаем (доступ и так
    зафейлится на первом инструменте). Ниже min_supported — выходим (форсим обновление).
    """
    try:
        info = (_get_client().get("/api/v1/me") or {}).get("client") or {}
    except Exception:
        return
    cur = _vtuple(__version__)
    minv, latest = info.get("min_supported_version"), info.get("latest_version")
    upgrade = info.get("upgrade") or "pipx upgrade ai-lvl-mcp"
    if minv and cur < _vtuple(minv):
        print(f"⛔ ai-lvl-mcp {__version__} ниже минимально поддерживаемой {minv}. "
              f"Обновитесь: {upgrade}", file=sys.stderr)
        sys.exit(1)
    if latest and cur < _vtuple(latest):
        print(f"ℹ ai-lvl-mcp: установлена {__version__}, доступна {latest}. "
              f"Обновление: {upgrade}", file=sys.stderr)


def run() -> None:
    _check_version()
    mcp.run()  # stdio transport

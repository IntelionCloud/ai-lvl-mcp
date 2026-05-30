"""FastMCP stdio-сервер. Инструменты проксируют на sync-api /api/v1/me/* под JWT сотрудника.

Все инструменты read-only и автоматически ограничены доступными сотруднику spaces
(ACL считается на стороне sync-api). Если сотрудник не залогинен — инструмент вернёт
понятную ошибку с подсказкой `ai-lvl-mcp login`.
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP
from pydantic import Field

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


def run() -> None:
    mcp.run()  # stdio transport

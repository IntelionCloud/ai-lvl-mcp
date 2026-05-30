"""CLI: `ai-lvl-mcp login | whoami | logout | serve` (по умолчанию — serve/stdio MCP)."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

from .client import AiLvlClient, AuthError
from .config import (
    DEFAULT_HOST, clear_refresh_token, get_refresh_token, load_config,
    save_config, set_refresh_token,
)


def _cmd_login(args: argparse.Namespace) -> int:
    cfg = load_config()
    host = args.host or cfg["host"] or DEFAULT_HOST
    email = args.email or cfg["email"] or input("email: ").strip()
    password = os.environ.get("AI_LVL_PASSWORD") or getpass.getpass("пароль ai-lvl: ")
    try:
        client = AiLvlClient.login(host, email, password)
    except AuthError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    where = set_refresh_token(email, client.refresh_token)
    save_config(host, email)
    me = client.get("/api/v1/me")
    spaces = ", ".join(f"{s['slug']}({s['sensitivity']}{'+w' if s.get('writable') else ''})"
                       for s in me.get("spaces", [])) or "—"
    print(f"✓ вошли как {me.get('name') or email} @ {host}")
    print(f"  refresh-токен сохранён в {where}")
    print(f"  доступные spaces: {spaces}")
    if where == "file":
        print("  ⚠ keyring недоступен — токен в файле 0600. На десктопе лучше поставить keyring.",
              file=sys.stderr)
    return 0


def _cmd_whoami(_args: argparse.Namespace) -> int:
    cfg = load_config()
    if not cfg["email"]:
        print("не залогинен — `ai-lvl-mcp login`", file=sys.stderr)
        return 1
    token = get_refresh_token(cfg["email"])
    if not token:
        print("нет токена — `ai-lvl-mcp login`", file=sys.stderr)
        return 1
    try:
        me = AiLvlClient(cfg["host"], cfg["email"], token).get("/api/v1/me")
    except AuthError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    print(json.dumps(me, ensure_ascii=False, indent=2))
    return 0


def _cmd_logout(_args: argparse.Namespace) -> int:
    cfg = load_config()
    if cfg["email"]:
        clear_refresh_token(cfg["email"])
        print(f"✓ токен {cfg['email']} удалён")
    return 0


def _cmd_serve(_args: argparse.Namespace) -> int:
    from .server import run
    run()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="ai-lvl-mcp", description="ai-lvl knowledge MCP для сотрудника")
    sub = parser.add_subparsers(dest="cmd")

    p_login = sub.add_parser("login", help="войти (email+пароль → refresh-токен в keychain)")
    p_login.add_argument("--host", default=None, help=f"по умолчанию {DEFAULT_HOST}")
    p_login.add_argument("--email", default=None)
    p_login.set_defaults(func=_cmd_login)

    sub.add_parser("whoami", help="кто я + доступные spaces").set_defaults(func=_cmd_whoami)
    sub.add_parser("logout", help="удалить сохранённый токен").set_defaults(func=_cmd_logout)
    sub.add_parser("serve", help="запустить stdio MCP-сервер (по умолчанию)").set_defaults(func=_cmd_serve)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        args.func = _cmd_serve  # без аргументов — MCP-сервер (так его запускает Claude)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()

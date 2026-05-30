# ai-lvl-mcp

Локальный MCP-сервер, который сотрудник ставит себе (Claude Code / Claude Desktop / Cursor),
логинится своими **ai-lvl**-кредами и получает поиск по знаниям, **ограниченный его spaces**.

- Авторизация: email+пароль → `ai-lvl.intelion.cloud` выдаёт refresh-токен (хранится в OS-keychain)
  и короткоживущий access JWT (только в памяти). Сервер сам обновляет access.
- Доступ: read-only. Какие spaces видны — решает `employees.yaml` на сервере (ACL
  `accessible_spaces_for`), клиент ничего не «расширяет».
- Инструменты: `whoami`, `list_spaces`, `search`, `get_node`, `recent_changes`, `similar`.

> Запись (push заметок) сюда **не входит** — это отдельный поток (Obsidian-плагин / edit-bot),
> см. `docs/obsidian-plugin-spec.md`.

## Установка

Требуется Python ≥ 3.10. Рекомендуется [pipx](https://pipx.pypa.io) или `uv tool`:

```bash
pipx install git+https://github.com/IntelionCloud/ai-lvl-mcp.git
# или из локального клона:
pipx install .
```

Репозиторий публичный — для установки ничего, кроме доступа в интернет, не нужно. Креды
ai-lvl нужны только на шаге `ai-lvl-mcp login` (доступ к знаниям, не к коду).

## Шаг 1 — войти (один раз)

```bash
ai-lvl-mcp login            # спросит email и пароль ai-lvl (как в Forgejo)
ai-lvl-mcp whoami           # проверить: кто я и какие spaces доступны
```

Refresh-токен ляжет в keychain (на Linux без keyring-бэкенда — в `~/.ai-lvl/refresh-*.token`, 0600).
Хост по умолчанию `https://ai-lvl.intelion.cloud` (переопределяется `--host` или `AI_LVL_HOST`).

## Шаг 2 — подключить к клиенту

### Claude Code

```bash
claude mcp add ai-lvl -- ai-lvl-mcp serve
```

### Claude Desktop / Cursor (`claude_desktop_config.json` / mcp.json)

```json
{
  "mcpServers": {
    "ai-lvl": { "command": "ai-lvl-mcp", "args": ["serve"] }
  }
}
```

Перезапустить клиент — появятся инструменты `ai-lvl: search / get_node / whoami / …`.

## Headless / CI

Без интерактива логин можно сделать через env (например, в Docker-агенте):

```bash
AI_LVL_HOST=https://ai-lvl.intelion.cloud AI_LVL_EMAIL=you@intelion.cloud \
  AI_LVL_PASSWORD='...' ai-lvl-mcp login
```

## Отзыв доступа

Сервер хранит refresh-токены отзываемо (`auth.db`). Админ помечает `revoked=1` — устройство
теряет доступ сразу (access живёт ≤1 ч). Локально: `ai-lvl-mcp logout`.

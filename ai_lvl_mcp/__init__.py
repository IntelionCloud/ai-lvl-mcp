"""ai-lvl-mcp — локальный MCP-сервер для доступа сотрудника к knowledge layer ai-lvl.

Сотрудник логинится своими ai-lvl кредами (email+пароль), refresh-токен лежит в
OS-keychain, а MCP-инструменты отдают search/get_node/list_spaces, ограниченные его
доступными spaces (ACL на стороне sync-api, /api/v1/me/*).
"""

__version__ = "0.1.0"

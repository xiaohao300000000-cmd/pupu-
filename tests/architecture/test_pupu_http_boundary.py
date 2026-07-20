import ast
from pathlib import Path

PUPU_INTEGRATION = Path("src/pupu_assistant/integrations/pupu")
FORBIDDEN_MODULES = {"aiohttp", "httpx", "requests"}


def imported_top_level_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".", maxsplit=1)[0])
    return modules


def test_only_pupu_http_client_may_import_network_libraries() -> None:
    client_path = PUPU_INTEGRATION / "client.py"
    assert client_path.exists()

    violations = {
        str(path): sorted(imported_top_level_modules(path) & FORBIDDEN_MODULES)
        for path in PUPU_INTEGRATION.glob("*.py")
        if path.name != "client.py"
        and imported_top_level_modules(path) & FORBIDDEN_MODULES
    }

    assert violations == {}

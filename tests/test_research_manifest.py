import json
from pathlib import Path

import pytest

MANIFEST = Path("docs/research/upstreams.json")
REQUIRED_REPOSITORIES = {
    "cddjr/check",
    "YDEKQ/check",
    "jo-dean/check",
    "CHERWING/CHERWIN_SCRIPTS",
    "fghwett/pupu",
    "Churroser/PupuTool",
}
REQUIRED_FIELDS = {
    "repository_url",
    "inspected_sha",
    "inspected_at",
    "license",
    "pupu_files",
    "seal_result",
    "sign_result",
    "cart_result",
}


def test_research_manifest_covers_required_repositories() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    repositories = {entry["repository"] for entry in data["repositories"]}

    assert repositories >= REQUIRED_REPOSITORIES


@pytest.mark.parametrize("repository", sorted(REQUIRED_REPOSITORIES))
def test_research_manifest_has_traceable_conclusions(repository: str) -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entry = next(item for item in data["repositories"] if item["repository"] == repository)

    assert entry.keys() >= REQUIRED_FIELDS
    assert len(entry["inspected_sha"]) == 40
    assert entry["repository_url"] == f"https://github.com/{repository}"
    assert entry["pupu_files"]
    assert entry["seal_result"] in {"absent", "partial", "complete"}
    assert entry["sign_result"] in {"absent", "partial", "complete"}
    assert entry["cart_result"] in {"absent", "read_only", "write_only", "complete"}

from pathlib import Path


def test_public_validator_script_exists_and_uses_package_boundary() -> None:
    script = Path("scripts/validate_pupu_public.py")
    assert script.exists()

    source = script.read_text(encoding="utf-8")
    assert "PupuSystemService" in source
    assert "PupuHttpClient" in source
    assert "httpx.get(" not in source
    assert "requests." not in source


def test_protected_validator_script_exists_and_uses_private_template() -> None:
    script = Path("scripts/validate_pupu_protected.py")
    template = Path(".local/pupu-live-request.example.json")
    assert script.exists()
    assert template.exists()

    source = script.read_text(encoding="utf-8")
    assert "BlackboxPupuSignatureService" in source
    assert "PupuHttpClient" in source
    assert ".local/private/pupu-live-request.json" in source
    assert "httpx.get(" not in source
    assert "requests." not in source

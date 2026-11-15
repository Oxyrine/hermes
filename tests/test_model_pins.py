import re
import tomllib
from pathlib import Path

CFG = Path(__file__).parent.parent / "src" / "hermes" / "models.toml"


def test_pins_are_free_tier_flash_and_flash_lite_only():
    text = CFG.read_text(encoding="utf-8")
    models = tomllib.loads(text)["models"]
    assert "flash-lite" in models["flash_lite"] and "flash" in models["flash"]
    assert not re.search(r"gemini-[\w.-]*pro", text.lower())

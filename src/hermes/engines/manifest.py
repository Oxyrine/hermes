"""Rule-version guard support. `python -m hermes.engines.manifest` records the current hash
of every engine under its rule version in manifest.json. It refuses to overwrite a version
already recorded with a different hash: bump `version` in rules.json instead."""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
MANIFEST = ROOT / "manifest.json"


def engine_dirs() -> list[Path]:
    return sorted(p.parent for p in ROOT.glob("*/rules.json"))


def engine_hash(d: Path) -> str:
    """Hash of every .py file and rules.json in the engine dir (line endings normalised)."""
    h = hashlib.sha256()
    for f in sorted([*d.glob("*.py"), d / "rules.json"]):
        h.update(f.name.encode() + b"\0" + f.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def current() -> dict[str, tuple[str, str]]:
    """engine name -> (rule version, hash)."""
    return {
        d.name: (json.loads((d / "rules.json").read_text("utf-8"))["version"], engine_hash(d))
        for d in engine_dirs()
    }


def recorded() -> dict:
    return json.loads(MANIFEST.read_text("utf-8")) if MANIFEST.exists() else {}


def main() -> int:
    m = recorded()
    for name, (version, h) in current().items():
        if m.setdefault(name, {}).setdefault(version, h) != h:
            print(f"{name} {version}: changed without a version bump; bump rules.json version")
            return 1
    MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Guard: an engine (or its rules.json) may not change without a rule version bump.
Covers every engine dir under src/hermes/engines/ that has a rules.json, present and future."""

import pytest

from hermes.engines import manifest

CURRENT = manifest.current()


def test_engines_discovered():
    assert "interest" in CURRENT


@pytest.mark.parametrize("name", sorted(CURRENT))
def test_engine_changed_requires_version_bump(name):
    version, h = CURRENT[name]
    recorded = manifest.recorded().get(name, {})
    assert version in recorded, (
        f"{name} {version} is not in manifest.json: run `uv run python -m hermes.engines.manifest`"
    )
    assert recorded[version] == h, (
        f"{name} changed without a version bump: bump `version` in its rules.json, "
        f"then run `uv run python -m hermes.engines.manifest`"
    )

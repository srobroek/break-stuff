#!/usr/bin/env python3
"""Shim: regenerate the apm.yml ``marketplace:`` block.

The rendering moved to the canonical render system (render-docs.py +
build_inventory.py). This thin entrypoint is kept so CI's build-artifacts.yml
and the apm.yml ``scripts:`` map can keep calling the same script name. It
delegates to ``render-docs.py marketplace-block`` and forwards ``--check``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODEX_MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"


def _load_inventory():
    spec = importlib.util.spec_from_file_location(
        "build_inventory", Path(__file__).with_name("build_inventory.py")
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def filter_codex_marketplace(
    path: Path,
    allowed_packages: set[str],
    *,
    check: bool = False,
) -> bool:
    """Remove packages that do not target Codex from an APM-packed catalog."""
    if not path.is_file():
        return False
    marketplace = json.loads(path.read_text(encoding="utf-8"))
    plugins = marketplace.get("plugins") or []
    filtered = [plugin for plugin in plugins if plugin.get("name") in allowed_packages]
    if filtered == plugins:
        return False
    if check:
        return True
    marketplace["plugins"] = filtered
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(marketplace, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return True


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    check = "--check" in args
    render_result = _render_main()(["marketplace-block", *args])
    if render_result:
        return render_result
    inventory = _load_inventory().build_context()
    allowed = {
        package["name"] for package in inventory["packages"] if "codex" in package["targets"]
    }
    filtered = filter_codex_marketplace(CODEX_MARKETPLACE, allowed, check=check)
    if filtered:
        print(
            "Codex marketplace contains packages that do not target Codex."
            if check
            else "Filtered non-Codex packages from the Codex marketplace."
        )
    return 1 if check and filtered else 0


def _render_main():
    spec = importlib.util.spec_from_file_location(
        "render_docs", Path(__file__).with_name("render-docs.py")
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod.main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

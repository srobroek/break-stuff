#!/usr/bin/env python3
"""Shim: regenerate release-please-config.json + .release-please-manifest.json.

The rendering moved to the canonical render system (render-docs.py +
build_inventory.py). This thin entrypoint is kept so CI's build-artifacts.yml
and the apm.yml ``scripts:`` map can keep calling the same script name. It
delegates to ``render-docs.py release-please`` and forwards ``--check``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _render_main():
    spec = importlib.util.spec_from_file_location(
        "render_docs", Path(__file__).with_name("render-docs.py")
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod.main


if __name__ == "__main__":
    raise SystemExit(_render_main()(["release-please", *sys.argv[1:]]))

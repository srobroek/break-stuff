#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "jinja2>=3"]
# ///
"""Render every generated doc artifact from the single canonical inventory.

One inventory walk (``build_inventory.build_context``) feeds three renderers:

* ``readme-tables`` -- the marker-injected markdown tables in docs/*.md and the
  README intro count bullets, rendered via Jinja templates under .apm/templates/.
* ``marketplace-block`` -- rewrites the ``marketplace:`` block in apm.yml.
* ``release-please`` -- writes release-please-config.json + the manifest.

Why Jinja for some but not all: the docs tables and README intro are plain
string rendering, so they live as Jinja templates (easy to edit, byte-parity
trivially holds). The marketplace block is emitted by PyYAML's dumper and the
release-please files by ``json.dumps`` -- reproducing those serializers'
byte-exact quoting/escaping/wrapping in Jinja is fragile, so they keep the
original Python serialization and only take their dynamic data from the
inventory. The win is the SINGLE source of truth + ONE walk, not forcing every
format through a template engine.

Subcommands (each accepts --check to diff against the committed file and exit 1
on drift, mirroring the old per-script --check):

    render-docs.py readme-tables [--check]
    render-docs.py marketplace-block [--check]
    render-docs.py release-please [--check]
    render-docs.py all [--check]      # all three

The legacy entrypoints (build-readme-tables.py / build-marketplace-block.py /
build-release-please.py) are thin shims that call the matching subcommand, so
CI's build-artifacts.yml and the apm.yml scripts keep their names.

stdlib + PyYAML + Jinja2 (PyYAML and apm-cli are already CI deps; jinja2 is
added to the CI install).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / ".apm" / "templates"
APM_YML = ROOT / "apm.yml"
README = ROOT / "README.md"
CONFIG = ROOT / "release-please-config.json"
MANIFEST = ROOT / ".release-please-manifest.json"
PACKAGES_DIR = ROOT / "packages"


def _load_inventory():
    """Import build_inventory as a sibling module (works regardless of cwd)."""
    spec = importlib.util.spec_from_file_location(
        "build_inventory", Path(__file__).with_name("build_inventory.py")
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# Jinja environment
# --------------------------------------------------------------------------- #


def _escape_cell(text) -> str:
    """Make a string safe for one markdown table cell (mirrors the old
    escape_cell()): pipe-escape, flatten newlines, strip."""
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _jinja_env():
    from jinja2 import Environment, FileSystemLoader

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=False,  # markdown, not HTML
        keep_trailing_newline=False,  # templates control their own trailing newline
        trim_blocks=False,
        lstrip_blocks=False,
    )
    env.filters["cell"] = _escape_cell
    return env


# --------------------------------------------------------------------------- #
# readme-tables: docs/*.md table sections + README intro counts
# --------------------------------------------------------------------------- #


# Each section's (template, header row, row-builder). Row-builders take the
# inventory context and return a list of raw (un-escaped) cell lists.
def _rows_bundles(ctx):
    return [
        [f"`{p['name']}`", p["summary"], p["includes_resolved"]] for p in ctx["by_kind"]["bundle"]
    ]


def _rows_simple(kind):
    def build(ctx):
        return [[f"`{p['name']}`", p["description"]] for p in ctx["by_kind"][kind]]

    return build


def _rows_external_sources(ctx):
    rows = []
    for src in ctx["external_sources"]:
        repo = src["repo"]
        link = f"[`{repo}`](https://github.com/{repo})"
        members = ", ".join(f"`{m}`" for m in src["members"])
        rows.append([link, str(src["count"]), members])
    return rows


def _rows_external_repos(ctx):
    """Top-level marketplace entries hosted in another git repo (not packages/)."""
    rows = []
    for e in ctx.get("external_marketplace", []):
        repo = e.get("repo") or ""
        name = e["name"]
        link = f"[`{name}`](https://github.com/{repo})" if repo else f"`{name}`"
        ref = e.get("ref") or ""
        # A 40-char hex ref is a commit SHA -- show the short form; tags as-is.
        is_sha = len(ref) == 40 and all(c in "0123456789abcdef" for c in ref.lower())
        ref_disp = f"`{ref[:7]}`" if is_sha else (f"`{ref}`" if ref else "")
        tags = ", ".join(f"`{t}`" for t in e.get("tags") or [])
        rows.append([link, e.get("category", ""), ref_disp, tags])
    return rows


# marker -> (template name, headers, row-builder, target doc file)
TABLE_SECTIONS = {
    "bundles": (
        "bundles.jinja",
        ["Bundle", "What it gives you", "Includes"],
        _rows_bundles,
        "docs/bundles.md",
    ),
    "external-sources": (
        "external-sources.jinja",
        ["Source repo", "Count", "Members pulled"],
        _rows_external_sources,
        "docs/bundles.md",
    ),
    "external-repos": (
        "external-repos.jinja",
        ["Plugin", "Category", "Pinned ref", "Tags"],
        _rows_external_repos,
        "docs/external-repos.md",
    ),
    "skills": ("skills.jinja", ["Skill", "Description"], _rows_simple("skill"), "docs/skills.md"),
    "agents": ("agents.jinja", ["Agent", "Description"], _rows_simple("agent"), "docs/agents.md"),
    "steering": (
        "steering.jinja",
        ["Steering Package", "Description"],
        _rows_simple("steering"),
        "docs/steering.md",
    ),
    "hooks": (
        "hooks.jinja",
        ["Hook Package", "Description"],
        _rows_simple("hooks"),
        "docs/hooks-and-mcp.md",
    ),
    "mcp": (
        "mcp.jinja",
        ["MCP Package", "Description"],
        _rows_simple("mcp"),
        "docs/hooks-and-mcp.md",
    ),
}

# README intro counts: rendered template, injected into README.md.
_INTRO_MARKER = "intro-counts"
_INTRO_TEMPLATE = "readme-intro.jinja"


def _inject(text: str, marker: str, payload: str, *, path: str) -> str:
    begin = f"<!-- BEGIN:{marker} -->"
    end = f"<!-- END:{marker} -->"
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), flags=re.DOTALL)
    if not pattern.search(text):
        raise SystemExit(
            f"marker pair {begin} / {end} not found in {path} -- "
            "add the markers where the content should render"
        )
    replacement = f"{begin}\n{payload}\n{end}"
    return pattern.sub(lambda _: replacement, text)


def _render_readme_tables(ctx) -> dict[str, str]:
    """Render every marker-injected file. Returns {relpath: new_text}."""
    env = _jinja_env()

    # Group markers by their target file (matches the old by_file injection).
    by_file: dict[str, list[str]] = {}
    for marker, (_tpl, _hdr, _rows, rel) in TABLE_SECTIONS.items():
        by_file.setdefault(rel, []).append(marker)

    out: dict[str, str] = {}
    for rel, markers in by_file.items():
        path = ROOT / rel
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            tpl_name, headers, row_builder, _ = TABLE_SECTIONS[marker]
            payload = env.get_template(tpl_name).render(headers=headers, rows=row_builder(ctx))
            text = _inject(text, marker, payload, path=rel)
        out[rel] = text

    # README intro counts.
    readme_text = README.read_text(encoding="utf-8")
    intro_payload = env.get_template(_INTRO_TEMPLATE).render(counts=ctx["counts"])
    readme_text = _inject(readme_text, _INTRO_MARKER, intro_payload, path="README.md")
    out["README.md"] = readme_text

    return out


def cmd_readme_tables(ctx, check: bool) -> int:
    rendered = _render_readme_tables(ctx)
    stale: list[str] = []
    for rel, new_text in sorted(rendered.items()):
        path = ROOT / rel
        original = path.read_text(encoding="utf-8")
        if new_text == original:
            continue
        if check:
            stale.append(rel)
        else:
            path.write_text(new_text, encoding="utf-8")
            print(f"updated tables in {rel}")
    if check:
        if stale:
            print("Inventory tables out of date in: " + ", ".join(sorted(stale)))
            print("Run: apm run build-readme-tables")
            return 1
        print("Inventory tables are up to date.")
    return 0


# --------------------------------------------------------------------------- #
# marketplace-block: rewrite the marketplace: block in apm.yml
# --------------------------------------------------------------------------- #


class _IndentDumper(yaml.Dumper):
    """Indent block sequences under their key, matching apm.yml's hand style."""

    def increase_indent(self, flow=False, indentless=False):  # noqa: ARG002
        return super().increase_indent(flow, False)


def _render_marketplace_block(marketplace: dict, entries: list[dict]) -> str:
    block: dict = {}
    for key in marketplace:
        block[key] = entries if key == "packages" else marketplace[key]
    if "packages" not in block:
        block["packages"] = entries
    dumped = yaml.dump(
        block,
        Dumper=_IndentDumper,
        sort_keys=False,
        default_flow_style=False,
        width=10**9,
        allow_unicode=True,
        indent=2,
    )
    indented = "".join(
        ("  " + line if line.strip() else line) for line in dumped.splitlines(keepends=True)
    )
    return "marketplace:\n" + indented


def _regenerate_apm_yml(text: str) -> tuple[str, list[str]]:
    data = yaml.safe_load(text) or {}
    marketplace = data.get("marketplace")
    if not isinstance(marketplace, dict):
        raise SystemExit("apm.yml has no 'marketplace:' block to generate")

    inv = _load_inventory()
    ctx = inv.build_context(marketplace)
    entries = ctx["marketplace"]["entries"]
    warnings = ctx["marketplace"]["warnings"]
    block_text = _render_marketplace_block(marketplace, entries)

    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.rstrip("\n") == "marketplace:"), None)
    if start is None:
        raise SystemExit("could not locate the 'marketplace:' line in apm.yml")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if ln[:1].strip() and not ln.startswith(("#", " ", "\t")):
            end = i
            break

    head = "".join(lines[:start])
    tail = "".join(lines[end:])
    new_text = head + block_text
    if not new_text.endswith("\n"):
        new_text += "\n"
    new_text += tail
    return new_text, warnings


def cmd_marketplace_block(_ctx, check: bool) -> int:
    original = APM_YML.read_text(encoding="utf-8")
    updated, warnings = _regenerate_apm_yml(original)
    for w in warnings:
        print(f"[warn] {w}", file=sys.stderr)
    if updated == original:
        if check:
            print("marketplace block is up to date.")
        return 0
    if check:
        print("apm.yml marketplace block is out of date. Run: apm run build-marketplace-block")
        return 1
    APM_YML.write_text(updated, encoding="utf-8")
    n = len(yaml.safe_load(updated)["marketplace"]["packages"])
    print(f"regenerated marketplace block: {n} packages")
    return 0


# --------------------------------------------------------------------------- #
# release-please: config + manifest
# --------------------------------------------------------------------------- #

CHANGELOG_SECTIONS = [
    {"type": "feat", "section": "Features"},
    {"type": "fix", "section": "Bug Fixes"},
    {"type": "perf", "section": "Performance"},
    {"type": "refactor", "section": "Refactors"},
    {"type": "docs", "section": "Documentation"},
    {"type": "chore", "section": "Chores", "hidden": True},
    {"type": "test", "section": "Tests", "hidden": True},
    {"type": "ci", "section": "CI/CD", "hidden": True},
]


def _build_release_config(pkgs: list[str]) -> dict:
    # Root component is the repo's own apm.yml name, not a hardcoded monorepo id,
    # so a renamed repo (or a fork of this template) tags its root release
    # correctly instead of inheriting the original project's component.
    root_name = (yaml.safe_load(APM_YML.read_text(encoding="utf-8")) or {}).get(
        "name", "root"
    )
    packages = {}
    packages["."] = {
        "release-type": "simple",
        "component": root_name,
        "changelog-path": "CHANGELOG.md",
        "exclude-paths": ["packages"],
        "extra-files": [{"type": "yaml", "path": "apm.yml", "jsonpath": "$.version"}],
    }
    for p in pkgs:
        packages[f"packages/{p}"] = {
            "release-type": "simple",
            "component": p,
            "changelog-path": "CHANGELOG.md",
            "extra-files": [{"type": "yaml", "path": "apm.yml", "jsonpath": "$.version"}],
        }
    return {
        "$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
        "separate-pull-requests": False,
        # Double-dash separator: tags render as `{component}--v{version}`, the
        # convention Claude `/plugin` + Codex `plugin add` use for native version
        # resolution (APM's remote resolver matches `{name}--v{version}` only).
        # Existing single-dash tags are kept (backfilled) for back-compat.
        "tag-separator": "--",
        "include-component-in-tag": True,
        "changelog-sections": CHANGELOG_SECTIONS,
        "packages": packages,
    }


def _version_at(manifest: Path) -> str:
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    return str(data.get("version", "0.0.1"))


def _build_release_manifest(ctx, pkgs: list[str]) -> dict:
    versions = {p["dirname"]: p["version"] for p in ctx["packages"]}
    manifest = {".": _version_at(APM_YML)}
    manifest.update({f"packages/{p}": versions[p] for p in pkgs})
    return manifest


def cmd_release_please(ctx, check: bool) -> int:
    # Order packages by directory name, matching the old _package_dirs() walk.
    pkgs = sorted(p["dirname"] for p in ctx["packages"])
    config = _build_release_config(pkgs)
    manifest = _build_release_manifest(ctx, pkgs)
    config_text = json.dumps(config, indent=2) + "\n"
    manifest_text = json.dumps(manifest, indent=2) + "\n"

    if check:
        stale = []
        if not CONFIG.exists() or CONFIG.read_text() != config_text:
            stale.append("release-please-config.json")
        if not MANIFEST.exists() or MANIFEST.read_text() != manifest_text:
            stale.append(".release-please-manifest.json")
        if stale:
            print("release-please config out of date:", ", ".join(stale))
            print("Run: apm run build-release-please")
            return 1
        print("release-please config up to date.")
        return 0

    CONFIG.write_text(config_text, encoding="utf-8")
    MANIFEST.write_text(manifest_text, encoding="utf-8")
    print(f"wrote release-please config + manifest for {len(pkgs)} packages")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

_COMMANDS = {
    "readme-tables": cmd_readme_tables,
    "marketplace-block": cmd_marketplace_block,
    "release-please": cmd_release_please,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[*_COMMANDS, "all"],
        help="Which artifact(s) to render.",
    )
    parser.add_argument("--check", action="store_true", help="Diff vs committed; exit 1 on drift.")
    args = parser.parse_args(argv)

    inv = _load_inventory()
    ctx = inv.build_context()

    if args.command == "all":
        rc = 0
        # marketplace-block first (it reads/writes apm.yml independently), then
        # release-please, then readme-tables -- order matches build-artifacts.
        for name in ("marketplace-block", "release-please", "readme-tables"):
            rc |= _COMMANDS[name](ctx, args.check)
        return 1 if rc else 0

    return _COMMANDS[args.command](ctx, args.check)


if __name__ == "__main__":
    raise SystemExit(main())

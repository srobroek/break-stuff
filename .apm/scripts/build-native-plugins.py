#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Generate committed native plugin layout for every native-capable package.

The marketplace `source: ./packages/<name>` entries are consumed by three
loaders: Claude `/plugin install`, Codex `plugin add`, and APM `apm install`.
Claude and Codex have distinct required manifests (`.claude-plugin/plugin.json`
and `.codex-plugin/plugin.json`) and partly different component contracts. APM's
own `apm pack` only writes the catalogs plus a repo-root plugin.json; it never
materialises per-package native layout. This generator fills that gap.

It is the native-layout analogue of render-docs.py: driven by the single
`build_inventory.build_context()` walk, idempotent, and supports `--check` for a
CI staleness gate. Generated files are committed (like the marketplace block) so a
fresh clone resolves marketplace sources with no build step.

What it emits, per package classification:

* skill  -> both manifests reference `.apm/skills` in place
* agent  -> `agents/<n>.md` (native agent discovery; APM additionally converts
  target-matched `.apm/agents/*.agent.md` sources for Claude or Codex)
* mcp    -> Claude `.mcp.json` plus Codex `.codex.mcp.json`, because the runtimes
  require different wrapper shapes
* bundle -> Claude manifest with `dependencies`; Codex has no native dependency
  field, so bundle composition remains an APM-only capability
* hooks / mixed packages with hooks -> shared `hooks/hooks.json` when variants
  match, otherwise target-specific hook files referenced by each manifest
* steering -> metadata-only manifests; native plugins have no rules/instructions
  component, so APM remains required to deliver the actual steering.

`plugin.json` carries name/version/description/author/license, plus
`dependencies` for bundles. Component dirs are auto-discovered by all three
loaders, so no path-override keys are written.

stdlib + PyYAML only (PyYAML already a CI dep via apm-cli).
"""

from __future__ import annotations

import argparse
import filecmp
import importlib.util
import json
import re
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PACKAGES_DIR = ROOT / "packages"
APM_YML = ROOT / "apm.yml"

# Native component dirs/files this generator owns at a package root. Any of these
# present-but-unexpected is pruned so the tree never drifts from the source.
_GENERATED_DIRS = ("skills", "agents", "hooks", ".claude-plugin", ".codex-plugin")
_GENERATED_FILES = (".mcp.json", ".codex.mcp.json")

# A first-party dependency reference -> the member package name (for bundles).
# "First-party" means a package THIS repo's marketplace also ships, since a native
# `dependencies` entry resolves by plugin id within the installed marketplace set.
# The pattern is built from packages/ below rather than hardcoding a repo slug: the
# hardcoded `srobroek/agentic-packages` survived the extract into this standalone
# repo and kept emitting `beads` as a dependency of a marketplace that does not
# ship it, so `claude plugin install sabot@sabot` installed and then refused to
# enable ("Dependency \"beads@sabot\" is not installed").
_DEP_REF = re.compile(r"([\w-]+)/packages/([\w-]+)(?:#(.+))?$")


def _first_party_names() -> frozenset[str]:
    """Package names this repo's own marketplace ships."""
    if not PACKAGES_DIR.is_dir():
        return frozenset()
    return frozenset(p.name for p in PACKAGES_DIR.iterdir() if p.is_dir())


def _load_inventory():
    spec = importlib.util.spec_from_file_location(
        "build_inventory", Path(__file__).with_name("build_inventory.py")
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _author_license(root_manifest: dict) -> tuple[dict | None, str | None]:
    """Repo-level author/license, used when a package omits its own."""
    author = root_manifest.get("author")
    author_obj = {"name": str(author)} if isinstance(author, str) else author
    return author_obj, root_manifest.get("license")


# --------------------------------------------------------------------------- #
# plugin.json
# --------------------------------------------------------------------------- #


def _plugin_manifest(
    pkg: dict,
    manifest: dict,
    defaults: tuple,
    *,
    target: str,
    deps: list[str] | None = None,
    has_skills: bool = False,
    has_mcp: bool = False,
    hook_path: str | None = None,
) -> dict:
    author_default, license_default = defaults
    out: dict = {"name": pkg["name"]}
    if pkg.get("version"):
        out["version"] = str(pkg["version"])
    if pkg.get("description"):
        out["description"] = pkg["description"]
    author = manifest.get("author")
    author = {"name": str(author)} if isinstance(author, str) else (author or author_default)
    if author:
        out["author"] = author
    lic = manifest.get("license") or license_default
    if lic:
        out["license"] = str(lic)
    # Reference skills in place rather than copying them (avoids duplicating
    # any test_*.py the skill ships, which breaks pytest collection).
    if has_skills:
        out["skills"] = "./.apm/skills"
    if target == "codex" and has_mcp:
        out["mcpServers"] = "./.codex.mcp.json"
    if hook_path:
        out["hooks"] = hook_path
    if target == "claude" and deps:
        out["dependencies"] = deps
    return out


# --------------------------------------------------------------------------- #
# bundle dependencies
# --------------------------------------------------------------------------- #


def _bundle_dependencies(deps: list[object], *, target: str) -> list[str]:
    """Map a bundle's first-party apm deps to native plugin `dependencies`.

    Only first-party members (this repo's own packages) are emitted -- they
    resolve within the same generated marketplace. External members (e.g.
    `wshobson/*`) need a cross-marketplace allowlist and are intentionally NOT
    auto-added here (a native install would fail to resolve them otherwise).

    Entries are the bare PLUGIN NAME. Both consumers of this field take a plugin
    id: Claude Code accepts a string or `{name, version}` and rejects anything
    else, and apm's own `Plugin` model types the field `list[str]`. An earlier
    version emitted apm's `{git, path}` source-locator form here, which is the
    shape of an apm.yml dependency REFERENCE rather than of a resolved plugin id;
    `claude plugin validate` failed the whole manifest on it
    ("dependencies.0: Invalid input"), so `claude plugin install` could not
    install the package at all.
    """
    first_party = _first_party_names()
    out: list[str] = []
    for dep in deps:
        if isinstance(dep, dict):
            targets = {str(value) for value in dep.get("targets") or []}
            if targets and target not in targets:
                continue
            git = str(dep.get("git") or dep.get("id") or "").rstrip("/")
            path = str(dep.get("path") or "").strip("/")
            locator = "/".join(part for part in (git, path) if part)
        else:
            locator = str(dep)
        m = _DEP_REF.search(locator)
        name = m.group(2) if m else locator
        if name in first_party and name not in out:
            out.append(name)
    return out


# --------------------------------------------------------------------------- #
# agents
# --------------------------------------------------------------------------- #

# Frontmatter keys Claude Code refuses on a PLUGIN-shipped agent, as opposed to a
# user-level one under ~/.claude/agents. Each grants the child authority the
# installing user never reviewed, so the loader drops it rather than honoring a
# plugin's self-declared escalation.
_CLAUDE_AGENT_DROP = ("permissionMode", "hooks", "mcpServers")


def _claude_agent(path: Path) -> bytes:
    """An `.apm` agent source rewritten for the Claude plugin agent contract.

    The APM source is shared across runtimes and carries `permissionMode`, which
    APM honors and Claude Code does not accept from a plugin. Stripping it here
    keeps one source of truth while emitting a loadable agent.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return text.encode("utf-8")
    end = text.find("\n---", 4)
    if end == -1:
        return text.encode("utf-8")
    front, rest = text[4:end], text[end:]
    kept = [
        line
        for line in front.splitlines()
        if not any(line.startswith(f"{key}:") for key in _CLAUDE_AGENT_DROP)
    ]
    return ("---\n" + "\n".join(kept) + rest).encode("utf-8")


# --------------------------------------------------------------------------- #
# mcp -> .mcp.json
# --------------------------------------------------------------------------- #


def _mcp_servers(manifest: dict) -> dict | None:
    """Build the common MCP server map from `dependencies.mcp`."""
    servers = (manifest.get("dependencies") or {}).get("mcp") or []
    if not servers:
        return None
    out: dict = {}
    for s in servers:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        name = str(s["name"])
        entry: dict = {}
        transport = s.get("transport", "stdio")
        if s.get("command"):
            entry["command"] = str(s["command"])
            if s.get("args"):
                entry["args"] = list(s["args"])
            if s.get("env"):
                entry["env"] = dict(s["env"])
        elif s.get("url"):
            # http/sse server
            entry["type"] = transport if transport in ("http", "sse") else "http"
            entry["url"] = str(s["url"])
        else:
            continue
        out[name] = entry
    return out or None


# --------------------------------------------------------------------------- #
# hooks: resolve shared or target-specific sources
# --------------------------------------------------------------------------- #


def _hook_sources(pkg_dir: Path) -> tuple[Path | None, Path | None]:
    """Return `(claude, codex)` hook sources for a package.

    A bare `.apm/hooks/hooks.json` is explicitly universal. Legacy target-named
    variants are resolved independently so a Claude-only event can never leak
    into the Codex plugin. The caller decides whether matching files can share
    `hooks/hooks.json` or need separate native files.
    """
    hooks_dir = pkg_dir / ".apm" / "hooks"
    if not hooks_dir.is_dir():
        return None, None
    universal = hooks_dir / "hooks.json"
    if universal.is_file():
        return universal, universal
    claude = sorted(hooks_dir.glob("*-claude-hooks.json")) or sorted(
        hooks_dir.glob("claude-hooks.json")
    )
    codex = sorted(hooks_dir.glob("*-codex-hooks.json")) or sorted(
        hooks_dir.glob("codex-hooks.json")
    )
    return (claude[0] if claude else None, codex[0] if codex else None)


def _plan_hooks(
    pkg_dir: Path,
    plan: dict[str, object],
    targets: set[str],
) -> tuple[str | None, str | None]:
    """Add native hook files and return manifest paths for Claude and Codex."""
    claude, codex = _hook_sources(pkg_dir)
    if "claude" not in targets:
        claude = None
    if "codex" not in targets:
        codex = None
    if claude is None and codex is None:
        return None, None
    if claude is not None and codex is not None and filecmp.cmp(claude, codex, shallow=False):
        path = "./hooks/hooks.json"
        plan[path.removeprefix("./")] = claude.read_text(encoding="utf-8")
        return path, path

    claude_path = None
    codex_path = None
    if claude is not None:
        claude_path = "./hooks/claude-hooks.json"
        plan[claude_path.removeprefix("./")] = claude.read_text(encoding="utf-8")
    if codex is not None:
        codex_path = "./hooks/codex-hooks.json"
        plan[codex_path.removeprefix("./")] = codex.read_text(encoding="utf-8")
    return claude_path, codex_path


# --------------------------------------------------------------------------- #
# planning: compute the desired native tree for one package
# --------------------------------------------------------------------------- #


def _plan_package(pkg: dict, manifest: dict, defaults: tuple) -> dict[str, object] | None:
    """Return {relpath: content} for the native files a package should have.

    Content is bytes for copied files, str for generated JSON. Directory copies
    are represented as (src_dir, "<dir-copy>"). Returns None for steering (no
    native layout).
    """
    pkg_dir = PACKAGES_DIR / pkg["dirname"]
    targets = set(pkg.get("targets") or ("claude", "codex"))

    plan: dict[str, object] = {}
    claude_hook_path, codex_hook_path = _plan_hooks(pkg_dir, plan, targets)

    # Steering has no native rules/instructions component. Pure steering gets
    # metadata-only manifests so catalog entries remain structurally valid;
    # hybrid steering packages can additionally expose their hooks.

    # Skills are REFERENCED in place via a plugin.json `skills` override pointing
    # at .apm/skills -- NOT copied. All three native loaders (Claude /plugin,
    # Codex plugin add, apm install) honor the override. Copying would duplicate
    # any test_*.py the skill ships, and pytest's collector aborts on two modules
    # with the same basename. Multi-primitive bundles (e.g. speckit) surface their
    # skills the same way.
    skills_src = pkg_dir / ".apm" / "skills"
    has_skills = skills_src.is_dir() and any(skills_src.rglob("SKILL.md"))

    # Agents MUST be materialised at native agents/*.md: a plugin.json `agents`
    # override into .apm/ does not load (verified). Agents are .md only (no test
    # files), so copying carries no pytest-collision risk.
    agents_src = pkg_dir / ".apm" / "agents"
    if "claude" in targets and agents_src.is_dir():
        for f in sorted(agents_src.glob("*.agent.md")):
            plan[f"agents/{f.name[: -len('.agent.md')]}.md"] = _claude_agent(f)
        for f in sorted(agents_src.glob("*.md")):
            if not f.name.endswith(".agent.md"):
                plan[f"agents/{f.name}"] = _claude_agent(f)

    # MCP servers declared in the apm.yml dependencies.mcp block -> .mcp.json.
    mcp = _mcp_servers(manifest)
    if mcp is not None and "claude" in targets:
        plan[".mcp.json"] = json.dumps({"mcpServers": mcp}, indent=2, ensure_ascii=False) + "\n"
    if mcp is not None and "codex" in targets:
        # Codex accepts a direct server map or a wrapped `mcp_servers` object,
        # but not Claude's camel-case wrapper.
        plan[".codex.mcp.json"] = json.dumps(mcp, indent=2, ensure_ascii=False) + "\n"

    # Native plugin dependencies = this package's first-party apm members. Emit
    # them whenever they exist, independent of doc-classification: a skill-led
    # package (e.g. speckit) may still aggregate a first-party member, and it must
    # keep that wiring in its native plugin.json. Pure aggregators ("bundle") are
    # the common case but not the only one. _bundle_dependencies returns [] (->
    # None) when there are no first-party deps, so this is a no-op for standalone
    # packages like sniff.
    raw_deps = (manifest.get("dependencies") or {}).get("apm") or pkg["deps"]
    deps = _bundle_dependencies(raw_deps, target="claude") or None

    if "claude" in targets:
        plan[".claude-plugin/plugin.json"] = (
            json.dumps(
                _plugin_manifest(
                    pkg,
                    manifest,
                    defaults,
                    target="claude",
                    deps=deps,
                    has_skills=has_skills,
                    hook_path=claude_hook_path,
                ),
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )
    if "codex" in targets:
        plan[".codex-plugin/plugin.json"] = (
            json.dumps(
                _plugin_manifest(
                    pkg,
                    manifest,
                    defaults,
                    target="codex",
                    has_skills=has_skills,
                    has_mcp=mcp is not None,
                    hook_path=codex_hook_path,
                ),
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )
    return plan


# --------------------------------------------------------------------------- #
# apply / check
# --------------------------------------------------------------------------- #


def _materialize(pkg_dir: Path, plan: dict[str, object], check: bool) -> list[str]:
    """Write (or diff) the planned native files. Returns list of stale relpaths."""
    stale: list[str] = []

    # 1. Prune previously-generated dirs/files no longer in the plan. A plan key
    #    is either a DIRCOPY root (no slash, e.g. "skills") or a nested file
    #    (e.g. "agents/coder.md", "hooks/hooks.json") -- both contribute their
    #    top-level segment to the set of dirs that should exist.
    planned_dirs = {rel.split("/", 1)[0] for rel in plan}
    planned_files = set(plan)
    for d in _GENERATED_DIRS:
        target = pkg_dir / d
        wanted = d in planned_dirs
        if target.exists() and not wanted:
            if check:
                stale.append(f"{pkg_dir.name}/{d} (should be removed)")
            else:
                shutil.rmtree(target)
        elif target.is_dir():
            # These directories are fully generator-owned. Remove stale nested
            # files when a package changes from universal to target-specific
            # hooks, drops an agent, or stops emitting a manifest component.
            for nested in sorted(p for p in target.rglob("*") if p.is_file()):
                rel = nested.relative_to(pkg_dir).as_posix()
                if rel in planned_files:
                    continue
                if check:
                    stale.append(f"{pkg_dir.name}/{rel} (should be removed)")
                else:
                    nested.unlink()
    for f in _GENERATED_FILES:
        target = pkg_dir / f
        if target.exists() and f not in plan:
            if check:
                stale.append(f"{pkg_dir.name}/{f} (should be removed)")
            else:
                target.unlink()

    # 2. Write/diff each planned entry.
    for rel, content in plan.items():
        if isinstance(content, tuple) and content[0] == "DIRCOPY":
            src = content[1]
            dst = pkg_dir / rel
            stale += _sync_dir(src, dst, rel, pkg_dir.name, check)
            continue
        target = pkg_dir / rel
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        if target.exists() and target.read_bytes() == data:
            continue
        if check:
            stale.append(f"{pkg_dir.name}/{rel}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    return stale


def _sync_dir(src: Path, dst: Path, rel: str, pkg: str, check: bool) -> list[str]:
    """Mirror src -> dst exactly (content + membership). Returns stale relpaths."""
    stale: list[str] = []
    src_files = {p.relative_to(src) for p in src.rglob("*") if p.is_file()}
    dst_files = (
        {p.relative_to(dst) for p in dst.rglob("*") if p.is_file()} if dst.exists() else set()
    )

    for r in sorted(src_files):
        s, d = src / r, dst / r
        data = s.read_bytes()
        if d.exists() and d.read_bytes() == data:
            continue
        if check:
            stale.append(f"{pkg}/{rel}/{r}")
        else:
            d.parent.mkdir(parents=True, exist_ok=True)
            d.write_bytes(data)
    for r in sorted(dst_files - src_files):
        if check:
            stale.append(f"{pkg}/{rel}/{r} (should be removed)")
        else:
            (dst / r).unlink()
    return stale


CODEX_CATALOG = ROOT / ".agents/plugins/marketplace.json"


def _render_codex_catalog(ctx: dict) -> str:
    """Render the Codex marketplace catalog from the inventory walk.

    `apm pack` also writes this file, but it ignores each package's `target:` and
    so lists every marketplace member -- including the Claude-only ones (the six
    `lsp-*` packages, `agent-conformance`, `hooks-subagent-model`) and any
    external git member, none of which a Codex install can resolve from
    `./packages/<name>`. Owning it here keeps membership and `target:` in
    agreement and puts the file under `--check`, so drift fails CI instead of
    relying on someone reverting `apm pack`'s output by hand.
    """
    existing = json.loads(CODEX_CATALOG.read_text(encoding="utf-8"))
    entries = []
    for pkg in ctx["packages"]:
        if "codex" not in set(pkg.get("targets") or ()):
            continue
        entry = {
            "name": pkg["name"],
            "source": {"source": "local", "path": f"./packages/{pkg['dirname']}"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        }
        if pkg.get("category"):
            entry["category"] = pkg["category"]
        entries.append(entry)
    out = {k: v for k, v in existing.items() if k != "plugins"}
    out["plugins"] = sorted(entries, key=lambda e: e["name"])
    return json.dumps(out, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Diff vs committed; exit 1 on drift.")
    args = parser.parse_args(argv)

    inv = _load_inventory()
    ctx = inv.build_context()
    root_manifest = yaml.safe_load(APM_YML.read_text(encoding="utf-8")) or {}
    defaults = _author_license(root_manifest)

    all_stale: list[str] = []
    n_written = 0
    for pkg in ctx["packages"]:
        pkg_dir = PACKAGES_DIR / pkg["dirname"]
        manifest = yaml.safe_load((pkg_dir / "apm.yml").read_text(encoding="utf-8")) or {}
        plan = _plan_package(pkg, manifest, defaults)
        if plan is None:
            plan = {}
        stale = _materialize(pkg_dir, plan, args.check)
        if stale:
            all_stale.extend(stale)
        elif not args.check and plan:
            n_written += 1

    catalog = _render_codex_catalog(ctx)
    n_codex = len(json.loads(catalog)["plugins"])
    catalog_stale = CODEX_CATALOG.read_text(encoding="utf-8") != catalog
    if catalog_stale:
        if args.check:
            all_stale.append(".agents/plugins/marketplace.json")
        else:
            CODEX_CATALOG.write_text(catalog, encoding="utf-8")

    if args.check:
        if all_stale:
            print("Native plugin layout out of date:")
            for s in sorted(all_stale)[:40]:
                print(f"  {s}")
            if len(all_stale) > 40:
                print(f"  ... and {len(all_stale) - 40} more")
            print("Run: apm run build-native-plugins")
            return 1
        print("Native plugin layout is up to date.")
        return 0

    print(f"generated native plugin layout for {n_written} package(s)")
    if catalog_stale:
        print(f"regenerated Codex catalog: {n_codex} codex-target package(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Canonical package inventory: walk packages/*/apm.yml ONCE, emit one context.

This is the single source of dynamic data for every generated doc artifact. The
three thin generators (marketplace block, release-please config, README/docs
tables) all read this inventory instead of re-walking ``packages/`` and
re-deriving classification, includes resolution, and external-source grouping.

Why a shared module: before this, three scripts independently globbed
``packages/*/apm.yml`` and re-implemented the same parsing/classification. Drift
between them (e.g. a new classification rule applied in one but not another) was
a latent bug. The inventory centralises that walk and the derived facts.

stdlib + PyYAML only (PyYAML is already required by the existing generators and
provided transitively by ``pip install apm-cli`` in CI).

The emitted context dict (see :func:`build_context`) carries:

* ``packages`` -- per-package records sorted by name, each with
  ``name, description, version, type, target, targets, category, tags, source, deps,
  classification, is_bundle, includes_resolved`` (the resolved member list with
  first-party vs external ``^`` marking, matching the old README renderer).
* ``by_kind`` -- packages grouped by classification (bundle/skill/agent/
  steering/hooks/mcp), each list sorted by name.
* ``external_sources`` -- upstream repo -> sorted external member names.
* ``counts`` -- aggregate counts per kind plus ``total``.
* ``marketplace`` -- the rebuilt marketplace ``packages`` entry list (name,
  source, category, tags) plus warnings, for the YAML-block generator.

The marketplace ``category``/``tags`` curation (preserved from the existing
block when a package declares none) requires the current marketplace block as
input, so :func:`build_context` accepts the parsed root ``apm.yml`` data.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PACKAGES_DIR = ROOT / "packages"
APM_YML = ROOT / "apm.yml"

# A first-party member is a virtual-subdirectory dependency on this repo's own
# packages: "srobroek/agentic-packages/packages/<name>#<ref>".
_FIRST_PARTY = re.compile(r"srobroek/agentic-packages/packages/([\w-]+)")

# Per-entry key order in the rendered marketplace block. Local entries only ever
# carry name/source/category/tags, so the `if k in entry` filter leaves them
# byte-identical. The git-source fields (ref/subdir/version/tag_pattern) exist
# only on hand-authored EXTERNAL entries (a marketplace package whose `source` is
# a git repo, not ./packages/<dir>) and are slotted into canonical position here.
_MARKETPLACE_ENTRY_ORDER = (
    "name",
    "source",
    "ref",
    "subdir",
    "version",
    "tag_pattern",
    "category",
    "tags",
)

_SUPPORTED_TARGETS = ("claude", "codex")


def _package_targets(manifest: dict) -> tuple[str, list[str]]:
    """Return canonical package target metadata.

    Package manifests use the scalar ``target`` contract. ``all`` (and a
    missing target for compatibility with older packages) means both supported
    marketplace runtimes.
    """
    target = str(manifest.get("target") or "all")
    if target not in {"all", *_SUPPORTED_TARGETS}:
        raise ValueError(f"unsupported package target: {target}")
    targets = list(_SUPPORTED_TARGETS) if target == "all" else [target]
    return target, targets


def _load_manifest_path(path: Path) -> dict:
    """Parse a package apm.yml with a real YAML loader (never regex-scrape)."""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _apm_deps(manifest: dict) -> list[str]:
    """First-party + external apm dependency strings for a manifest."""
    deps = (manifest.get("dependencies") or {}).get("apm") or []
    out: list[str] = []
    for dep in deps:
        if isinstance(dep, str):
            out.append(dep)
        elif isinstance(dep, dict):
            git = str(dep.get("git") or dep.get("id") or "").rstrip("/")
            path = str(dep.get("path") or "").strip("/")
            ref = str(dep.get("ref") or "")
            locator = "/".join(part for part in (git, path) if part)
            out.append(f"{locator}#{ref}" if locator and ref else locator)
    return [d for d in out if d]


def _classify(name: str, pkg_dir: Path) -> str:
    """Classify a package by name + on-disk shape.

    Returns one of: agent, mcp, steering, hooks, skill, bundle. Identical to the
    rule the README generator used, lifted here verbatim so a single source owns
    classification.
    """
    skills = list((pkg_dir / ".apm" / "skills").glob("*/SKILL.md"))
    has_agents = (pkg_dir / ".apm" / "agents").is_dir()
    # The `agent-` prefix marks a dedicated agent package, but only when it
    # actually ships an agent under .apm/agents/. A package named `agent-*` that
    # is really a lone skill (one SKILL.md, no agents dir) -- e.g.
    # `agent-management`, a skill *about* managing agents -- must classify as a
    # skill, not an agent, so the prefix rule is guarded by on-disk shape.
    if name.startswith("agent-") and has_agents:
        return "agent"
    if name.startswith("mcp-"):
        return "mcp"
    if name.startswith("steering-") or name.startswith("language-steering-"):
        return "steering"
    if name.startswith("hooks-"):
        return "hooks"
    # Classify by the package's OWN primitives. A `bundle` is ONLY a pure
    # aggregator -- it ships no primitives of its own and exists to pull in other
    # packages via dependencies. A package that rolls its own skill(s) or
    # agent(s) is classified by those even when it ALSO has dependencies and even
    # when it ships several primitive types (e.g. `sniff` and `speckit` ship
    # skills + agents; they are skill packages, not bundles).
    if skills:
        return "skill"
    if has_agents:
        return "agent"
    return "bundle"


def _external_name(dep: str) -> str:
    """Short, readable name for a third-party dependency reference."""
    ref = dep.split("#", 1)[0].rstrip("/")
    return ref.rsplit("/", 1)[-1] if "/" in ref else ref


def _includes_resolved(deps: list[str]) -> str:
    """Render a bundle's members as an explicit list.

    First-party members are listed by bare name. Third-party members get a
    trailing ``^`` marker. ``^`` (not ``*``) avoids markdown emphasis parsing.
    """
    parts: list[str] = []
    for dep in deps:
        fp = _FIRST_PARTY.search(dep)
        if fp:
            parts.append(f"`{fp.group(1)}`")
        else:
            parts.append(f"`{_external_name(dep)}`^")
    return ", ".join(parts)


def _bundle_summary(description: str) -> str:
    """First clause of a bundle description, before the colon-introduced list."""
    text = description.strip()
    if ":" in text:
        head = text.split(":", 1)[0].strip()
        if head and len(head) <= 90:
            return head.rstrip(".")
    m = re.search(r"\.(?:\s|$)", text)
    head = text[: m.start()] if m else text
    return head.strip().rstrip(".")


def _existing_curation(marketplace: dict) -> dict[str, dict]:
    """Map package name -> {category, tags} from the current marketplace block."""
    out: dict[str, dict] = {}
    for entry in marketplace.get("packages") or []:
        if isinstance(entry, dict) and entry.get("name"):
            out[str(entry["name"])] = {
                "category": entry.get("category"),
                "tags": list(entry.get("tags") or []),
            }
    return out


def _is_local_source(source) -> bool:
    """A marketplace entry is LOCAL when its source is a ``./...`` relative path.

    APM derives ``PackageEntry.is_local`` the same way (a leading ``./`` marks a
    local-path package; every other string form -- ``owner/repo``,
    ``host.tld/owner/repo``, ``https://...`` -- and the dict/``type:`` form are
    remote git sources). Anything not local is an external entry this generator
    must preserve verbatim rather than regenerate from a packages/ dir.
    """
    return isinstance(source, str) and source.startswith("./")


def _external_repo_slug(source) -> str:
    """Best-effort ``owner/repo`` slug from an external marketplace source.

    Handles the string forms (``owner/repo``, ``host/owner/repo``,
    ``https://host/owner/repo[.git]``) and the dict/``type:`` form
    (``{repo: owner/repo}`` or ``{url: ...}``). Used only to build a GitHub link
    in the docs table; returns "" if it cannot parse a slug.
    """
    if isinstance(source, dict):
        source = source.get("repo") or source.get("url") or ""
    if not isinstance(source, str) or not source:
        return ""
    s = source.strip()
    s = s.removeprefix("https://").removeprefix("http://")
    if s.startswith("github.com/"):
        s = s[len("github.com/") :]
    s = s.removesuffix(".git")
    parts = [p for p in s.split("/") if p]
    # owner/repo lives in the FIRST two segments for owner/repo and
    # github.com/owner/repo forms (host already stripped above).
    if len(parts) >= 2 and "." not in parts[0]:
        return f"{parts[0]}/{parts[1]}"
    # host.tld/owner/repo (non-github host kept its dotted first segment).
    if len(parts) >= 3 and "." in parts[0]:
        return f"{parts[1]}/{parts[2]}"
    return ""


def _external_entries(marketplace: dict) -> dict[str, dict]:
    """Map name -> full entry for marketplace packages with an EXTERNAL source.

    These are hand-authored entries whose ``source`` points at a git repo (not a
    sibling ``./packages/<dir>``), so the packages/ walk never produces them. They
    are returned verbatim -- including ``source``/``ref``/``subdir``/category/tags
    -- so they round-trip through render-docs instead of being dropped.
    """
    out: dict[str, dict] = {}
    for entry in marketplace.get("packages") or []:
        if not (isinstance(entry, dict) and entry.get("name")):
            continue
        if _is_local_source(entry.get("source")):
            continue
        out[str(entry["name"])] = dict(entry)
    return out


def _package_own_tags(pkg: dict) -> list[str]:
    """A package's own tags (``tags`` plus ``keywords``, deduped, order-stable)."""
    tags: list[str] = []
    for key in ("tags", "keywords"):
        for t in pkg.get(key) or []:
            if t not in tags:
                tags.append(str(t))
    return tags


def build_context(marketplace: dict | None = None) -> dict:
    """Walk packages/*/apm.yml once and return the canonical context dict.

    ``marketplace`` is the parsed root apm.yml ``marketplace:`` block, used only
    to preserve ``category``/``tags`` curation for packages that declare none.
    When omitted it is read from the repo's apm.yml.
    """
    if marketplace is None:
        root = _load_manifest_path(APM_YML)
        marketplace = root.get("marketplace") or {}
    curation = _existing_curation(marketplace)
    external = _external_entries(marketplace)

    packages: list[dict] = []
    found: set[str] = set()
    marketplace_entries: list[dict] = []
    warnings: list[str] = []

    for manifest in sorted(PACKAGES_DIR.glob("*/apm.yml")):
        dirname = manifest.parent.name
        pkg = _load_manifest_path(manifest)
        name = str(pkg.get("name") or dirname)
        found.add(name)
        pkg_dir = manifest.parent
        deps = _apm_deps(pkg)
        target, targets = _package_targets(pkg)
        classification = _classify(name, pkg_dir)
        description = str(pkg.get("description") or "").strip()

        # --- doc-table record ---
        is_bundle = classification == "bundle"
        if is_bundle:
            includes = _includes_resolved(deps)
            if not includes:
                includes = "self-contained" if (pkg_dir / ".apm").is_dir() else "external packages"
        else:
            includes = ""

        # --- marketplace entry (category/tags curation) ---
        entry: dict = {"name": name, "source": f"./packages/{dirname}"}
        category = pkg.get("category") or curation.get(name, {}).get("category")
        if category:
            entry["category"] = str(category)
        tags = _package_own_tags(pkg) or curation.get(name, {}).get("tags") or []
        if tags:
            entry["tags"] = list(tags)
        if name not in curation and not entry.get("tags"):
            warnings.append(f"{name}: new package with no tags (add tags: to its apm.yml)")
        marketplace_entries.append({k: entry[k] for k in _MARKETPLACE_ENTRY_ORDER if k in entry})

        packages.append(
            {
                "name": name,
                "dirname": dirname,
                "description": description,
                "summary": _bundle_summary(description) if is_bundle else description,
                "version": str(pkg.get("version", "0.0.1")),
                "type": str(pkg.get("type") or ""),
                "target": target,
                "targets": targets,
                "category": entry.get("category", ""),
                "tags": entry.get("tags", []),
                "source": f"./packages/{dirname}",
                "deps": deps,
                "classification": classification,
                "is_bundle": is_bundle,
                "includes_resolved": includes,
            }
        )

    # Append hand-authored external entries (git-source packages with no
    # packages/ dir). Reshape through the canonical key order so git-source fields
    # land in stable position; preserve every key the author wrote. A name that
    # ALSO has a local packages/ dir is a collision -- the local dir wins (it is
    # the buildable source of truth) and the external entry is skipped with a
    # warning, so the block never carries two entries for one name. The surviving
    # ones are also collected as doc-table records (they live in another repo, so
    # the packages/* walk can't describe them).
    external_marketplace: list[dict] = []
    for name, entry in external.items():
        if name in found:
            warnings.append(
                f"{name}: external marketplace source ignored -- a packages/{name} "
                f"dir exists and takes precedence (remove one to resolve)"
            )
            continue
        marketplace_entries.append({k: entry[k] for k in _MARKETPLACE_ENTRY_ORDER if k in entry})
        external_marketplace.append(
            {
                "name": name,
                "source": entry.get("source"),
                "repo": _external_repo_slug(entry.get("source")),
                "ref": entry.get("ref", ""),
                "category": entry.get("category", ""),
                "tags": list(entry.get("tags") or []),
            }
        )

    # A curated name with no packages/ dir is "dropped" ONLY if it is not a
    # recognised external entry -- external sources are intentionally dir-less.
    for stale in sorted(set(curation) - found - set(external)):
        warnings.append(f"{stale}: in marketplace block but no packages/ dir -- dropped")

    packages.sort(key=lambda p: p["name"])
    marketplace_entries.sort(key=lambda e: e["name"])

    by_kind: dict[str, list[dict]] = {
        "bundle": [],
        "skill": [],
        "agent": [],
        "steering": [],
        "hooks": [],
        "mcp": [],
    }
    for p in packages:
        by_kind[p["classification"]].append(p)

    external_sources = _external_sources(packages)
    external_marketplace.sort(key=lambda e: e["name"])

    counts = {kind: len(items) for kind, items in by_kind.items()}
    counts["total"] = len(packages)

    return {
        "packages": packages,
        "by_kind": by_kind,
        "external_sources": external_sources,
        "external_marketplace": external_marketplace,
        "counts": counts,
        "marketplace": {
            "entries": marketplace_entries,
            "warnings": warnings,
        },
    }


def _external_sources(packages: list[dict]) -> list[dict]:
    """Group every external (non-first-party) member by its upstream repo.

    Returns a list of ``{repo, count, members}`` sorted by repo, with members
    sorted -- matching the old README external-sources renderer.
    """
    by_repo: dict[str, set[str]] = {}
    for p in packages:
        for dep in p["deps"]:
            if _FIRST_PARTY.search(dep):
                continue
            ref = dep.split("#", 1)[0].rstrip("/")
            parts = ref.split("/")
            if len(parts) < 2:
                continue
            repo = "/".join(parts[:2])
            by_repo.setdefault(repo, set()).add(parts[-1])
    return [
        {"repo": repo, "count": len(members), "members": sorted(members)}
        for repo, members in sorted(by_repo.items())
    ]


if __name__ == "__main__":  # pragma: no cover - manual inspection aid
    import json

    ctx = build_context()
    print(json.dumps({"counts": ctx["counts"]}, indent=2))

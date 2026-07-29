#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Inject package-owned model mappings into APM-generated Codex agents."""

from __future__ import annotations

import argparse
import os
import re
import sys
import tomllib
from pathlib import Path

import yaml

MAPPING_NAME = "agent-models.yml"
ALLOWED_CODEX_FIELDS = {"model", "reasoning_effort"}
AGENT_NAME = re.compile(r"^name:\s*[\"']?([^\"'\s]+)", re.MULTILINE)


class MappingError(ValueError):
    pass


def mapping_files(root: Path) -> list[Path]:
    candidates = [root / ".apm" / MAPPING_NAME]
    candidates.extend(root.glob(f"packages/*/.apm/{MAPPING_NAME}"))
    candidates.extend(root.glob(f"apm_modules/**/.apm/{MAPPING_NAME}"))
    candidates.extend(root.glob(f".apm/apm_modules/**/.apm/{MAPPING_NAME}"))
    return sorted({path.resolve() for path in candidates if path.is_file()})


def load_mappings(root: Path) -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    origins: dict[str, Path] = {}
    for path in mapping_files(root):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if document.get("version") != 1:
            raise MappingError(f"{path}: version must be 1")
        agents = document.get("agents") or {}
        if not isinstance(agents, dict):
            raise MappingError(f"{path}: agents must be a mapping")
        for name, runtime_data in agents.items():
            codex = runtime_data.get("codex") if isinstance(runtime_data, dict) else None
            if not isinstance(codex, dict) or not codex:
                raise MappingError(f"{path}: {name}.codex must be a non-empty mapping")
            unknown = set(codex) - ALLOWED_CODEX_FIELDS
            if unknown:
                raise MappingError(f"{path}: {name}.codex has unknown fields {sorted(unknown)}")
            if not codex.get("model") or not codex.get("reasoning_effort"):
                raise MappingError(f"{path}: {name}.codex requires model and reasoning_effort")
            normalized = {key: str(value) for key, value in codex.items()}
            if name in merged:
                if merged[name] == normalized:
                    continue  # identical re-declaration across bundles; first occurrence wins
                raise MappingError(
                    f"conflicting mapping for {name}:\n"
                    f"  {origins[name]}: {merged[name]}\n"
                    f"  {path}: {normalized}"
                )
            merged[str(name)] = normalized
            origins[str(name)] = path
    return merged


def agent_source_files(root: Path) -> list[Path]:
    # Check both authored package agent trees and the target-specific APM tree;
    # deployed `.codex/agents` coverage remains enforced by `patch_codex`.
    candidates = list(root.glob("packages/*/agents/*.md"))
    candidates.extend(root.glob("packages/*/.apm/agents/*.agent.md"))
    candidates.extend(root.glob(".apm/agents/*.agent.md"))
    return sorted({path.resolve() for path in candidates if path.is_file()})


def validate_source_coverage(root: Path, mappings: dict[str, dict[str, str]]) -> None:
    missing: list[str] = []
    for path in agent_source_files(root):
        match = AGENT_NAME.search(path.read_text(encoding="utf-8"))
        if match is None:
            raise MappingError(f"agent source has no frontmatter name: {path}")
        name = match.group(1)
        if name not in mappings:
            missing.append(f"agent source lacks {MAPPING_NAME} entry: {path} ({name})")
    if missing:
        raise MappingError("\n".join(missing))


def set_toml_string(text: str, key: str, value: str) -> str:
    line = f'{key} = "{value}"'
    pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(line, text, count=1)
    insert_at = text.find("\ndeveloper_instructions")
    if insert_at >= 0:
        return text[: insert_at + 1] + line + "\n" + text[insert_at + 1 :]
    return text.rstrip() + "\n" + line + "\n"


def expected_text(text: str, mapping: dict[str, str]) -> str:
    text = set_toml_string(text, "model", mapping["model"])
    return set_toml_string(
        text,
        "model_reasoning_effort",
        mapping["reasoning_effort"],
    )


def patch_codex(root: Path, mappings: dict[str, dict[str, str]], *, check: bool) -> int:
    agents_dir = root / ".codex" / "agents"
    errors: list[str] = []
    changed = 0
    deployed: dict[str, Path] = {}
    for path in sorted(agents_dir.glob("*.toml")):
        try:
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            errors.append(f"invalid deployed Codex agent {path}: {exc}")
            continue
        name = parsed.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"deployed Codex agent has no name: {path}")
            continue
        if name in deployed:
            errors.append(
                f"duplicate deployed Codex agent name {name}: {deployed[name]} and {path}"
            )
            continue
        deployed[name] = path

    for name, path in sorted(deployed.items()):
        if name not in mappings:
            errors.append(f"deployed Codex agent lacks {MAPPING_NAME} entry: {path} ({name})")

    for name, mapping in sorted(mappings.items()):
        path = deployed.get(name)
        if path is None:
            errors.append(f"missing deployed Codex agent: {agents_dir / f'{name}.toml'}")
            continue
        current = path.read_text(encoding="utf-8")
        desired = expected_text(current, mapping)
        try:
            parsed = tomllib.loads(desired)
        except tomllib.TOMLDecodeError as exc:
            errors.append(f"invalid generated TOML for {path}: {exc}")
            continue
        if parsed.get("model") != mapping["model"]:
            errors.append(f"model injection failed for {path}")
            continue
        if parsed.get("model_reasoning_effort") != mapping["reasoning_effort"]:
            errors.append(f"reasoning effort injection failed for {path}")
            continue
        if desired == current:
            continue
        changed += 1
        if not check:
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(desired, encoding="utf-8")
            os.replace(temporary, path)

    if errors:
        raise MappingError("\n".join(errors))
    verb = "need injection" if check else "injected"
    print(f"Codex agent models: {changed} {verb}; {len(mappings) - changed} already current")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Project root containing .codex/agents")
    parser.add_argument("--check", action="store_true", help="Report drift without writing")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    try:
        mappings = load_mappings(root)
        if not mappings:
            raise MappingError(f"no {MAPPING_NAME} files found below {root}")
        validate_source_coverage(root, mappings)
        changed = patch_codex(root, mappings, check=args.check)
    except MappingError as exc:
        print(f"agent model injection failed: {exc}", file=sys.stderr)
        return 1
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())

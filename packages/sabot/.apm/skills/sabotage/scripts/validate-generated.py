#!/usr/bin/env python3
"""Validate a generated artifact before anything depends on it.

    validate-generated.py --kind {rules,json,corpus,harness} PATH [--json] [--normalize]

Sabot generates rule files, harnesses, seed corpora, vectors, scenario JSON, and its own
report. Four measured failures say why generation is not evidence of a usable artifact:

  - A synthesized opengrep rule shipped COMMENTED OUT (`pv-react-table-not-virtualized`)
    and was recorded as skipped/INVALID rather than as a rule that never existed. A
    commented-out rule is valid YAML, so parsing cannot catch it; only "the tool loaded N
    rules" can.
  - One non-ASCII character in a rule file killed opengrep under the default locale: rc=2
    having scanned 0 files, with the PREVIOUS run's JSON still on disk reading as a clean
    scan.
  - `fuzz-cli.py` wrote zero-byte `.input` files, so every repro artifact was empty and
    only a reader who distrusted the output noticed.
  - One fuzzer reported authoring `fuzz/` trees that do not exist on disk at all, so
    existence and buildability both have to be asserted rather than assumed.

CHECKS, each reported independently so a caller sees which one failed: `exists`,
`non_empty`, `encoding`, `shape`, `not_commented_out`, `tool_load`, `compiles`.

The `shape` check on a rules file is a SHAPE CHECK, NOT A YAML PARSER. It looks for a
top-level `rules:` sequence, at least one `- id:` item, and no tab indentation. The real
gate is `tool_load`, which hands the file to the tool that will consume it and requires a
nonzero loaded-rule count.

SEMANTICS ARE OUT OF SCOPE. Whether a rule fires on a known-positive and stays silent on a
known-negative belongs to the briefs. A rule can pass every check here and still be
rejected on semantics; the checks are kept separable so that rejection stays possible.

EXIT CODES: 0 every check passed, 1 a check failed, 2 usage, 3 UNVALIDATED -- the
validating tool is absent, which is never a pass.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_UNVALIDATED = 3

PASS, FAIL, UNVALIDATED, SKIPPED = "pass", "fail", "unvalidated", "skipped"

# The runtime must be given the same locale the encoding check assumes, or the check and
# the scanner disagree about the same bytes.
LOCALE_ENV = {"LC_ALL": "C.UTF-8", "LANG": "C.UTF-8", "PYTHONUTF8": "1"}

# Typographic characters an LLM-authored rule file picks up unprompted. Anything outside
# this map still fails the encoding check; --normalize is not a licence to smuggle bytes.
NORMALIZE = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-",
    "…": "...", " ": " ", "→": "->", "·": "*",
}

_RULE_COUNT = re.compile(r"(\d+)\s+(?:valid\s+)?rules?\b", re.I)

COMPILERS = {
    ".py": lambda p: [sys.executable, "-m", "py_compile", str(p)],
    ".js": lambda p: ["node", "--check", str(p)],
    ".mjs": lambda p: ["node", "--check", str(p)],
    ".cjs": lambda p: ["node", "--check", str(p)],
    ".ts": lambda p: ["tsc", "--noEmit", str(p)],
    ".tsx": lambda p: ["tsc", "--noEmit", str(p)],
    ".go": lambda p: ["go", "vet", str(p)],
    ".rs": lambda p: ["cargo", "check", "--quiet"],
    ".sh": lambda p: ["shellcheck", str(p)],
}


class Report:
    def __init__(self, path: Path, kind: str):
        self.path, self.kind, self.checks = path, kind, []

    def add(self, name: str, status: str, detail: str) -> str:
        self.checks.append({"check": name, "status": status, "detail": detail})
        return status

    def status_of(self, name: str) -> str | None:
        return next((c["status"] for c in self.checks if c["check"] == name), None)

    def exit_code(self) -> int:
        if any(c["status"] == FAIL for c in self.checks):
            return EXIT_FAIL
        if any(c["status"] == UNVALIDATED for c in self.checks):
            return EXIT_UNVALIDATED
        return 0

    def as_dict(self) -> dict:
        return {
            "schema": "sabot-validate/1",
            "path": str(self.path),
            "kind": self.kind,
            "ok": self.exit_code() == 0,
            "exit_code": self.exit_code(),
            "checks": self.checks,
            "locale_env": LOCALE_ENV,
            "semantics": "out of scope: a rule may pass here and still fail on a control",
        }


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 300):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, **LOCALE_ENV})
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)


def check_exists(rep: Report) -> str:
    if rep.path.is_dir():
        return rep.add("exists", FAIL, f"{rep.path} is a directory, not a generated file")
    if not rep.path.exists():
        return rep.add(
            "exists", FAIL,
            f"{rep.path} does not exist. An artifact reported as authored and absent from "
            "disk is a coverage gap presented as coverage.",
        )
    return rep.add("exists", PASS, str(rep.path))


def check_non_empty(rep: Report) -> str:
    size = rep.path.stat().st_size
    if size == 0:
        return rep.add(
            "non_empty", FAIL,
            "0 bytes. A zero-byte artifact is a failure, never an empty result: a repro "
            "file with no content cannot reproduce or be minimized.",
        )
    return rep.add("non_empty", PASS, f"{size} bytes")


def check_encoding(rep: Report, normalize: bool) -> str:
    raw = rep.path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return rep.add("encoding", FAIL, f"not valid UTF-8 at byte {exc.start}: {exc.reason}")

    if normalize:
        fixed = text
        for bad, good in NORMALIZE.items():
            fixed = fixed.replace(bad, good)
        if fixed != text:
            rep.path.write_text(fixed, encoding="utf-8")
            text = fixed

    offenders = []
    lineno, col = 1, 1
    for index, ch in enumerate(text):
        if ch == "\n":
            lineno, col = lineno + 1, 1
            continue
        if ord(ch) > 127:
            offset = len(text[:index].encode("utf-8"))
            offenders.append(
                f"line {lineno} col {col} (byte {offset}): {ch!r} U+{ord(ch):04X}"
            )
        col += 1
    if offenders:
        return rep.add(
            "encoding", FAIL,
            "; ".join(offenders[:5])
            + ". One curly quote in a rule file made opengrep exit 2 having scanned 0 files "
            "under the default locale, and the previous run's JSON on disk read as clean. "
            f"Run with {LOCALE_ENV} and pass --normalize to rewrite these to ASCII.",
        )
    return rep.add("encoding", PASS, "ASCII only")


def _uncommented(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#"):
            out.append(line)
    return out


def check_not_commented_out(rep: Report, text: str) -> str:
    live = "\n".join(_uncommented(text))
    live_ids = re.findall(r"^\s*-?\s*id:\s*\S+", live, re.M)
    commented_ids = re.findall(r"^\s*#.*\bid:\s*\S+", text, re.M)
    if not live_ids and commented_ids:
        return rep.add(
            "not_commented_out", FAIL,
            f"every `id:` in this file is inside a comment ({len(commented_ids)} found). "
            "This is a rule that NEVER EXISTED, not a rule that was skipped: it is valid "
            "YAML, it loads zero rules, and its surface reports 0 findings.",
        )
    return rep.add("not_commented_out", PASS, f"{len(live_ids)} live rule id(s)")


def check_shape(rep: Report, text: str) -> str:
    live_lines = _uncommented(text)
    live = "\n".join(live_lines)
    problems = []
    if not re.search(r"^rules:\s*$", live, re.M):
        problems.append("no top-level `rules:` key")
    if not re.search(r"^\s*-\s*id:\s*\S", live, re.M):
        problems.append("no `- id:` sequence item under `rules:`")
    tabs = [i for i, ln in enumerate(text.splitlines(), 1)
            if ln[: len(ln) - len(ln.lstrip())].count("\t")]
    if tabs:
        problems.append(f"tab indentation on line(s) {tabs[:5]}; YAML forbids tabs")
    if problems:
        return rep.add("shape", FAIL, "; ".join(problems))
    return rep.add("shape", PASS, "top-level `rules:` with at least one `- id:` item")


def check_json(rep: Report) -> str:
    try:
        doc = json.loads(rep.path.read_text(errors="replace"))
    except ValueError as exc:
        return rep.add("shape", FAIL, f"not parseable JSON: {exc}")
    if doc in ({}, [], None):
        return rep.add(
            "shape", FAIL,
            "parses to an empty document. A scanner output blanked by a failed run reads "
            "as 0 findings; that is NOT EXECUTED.",
        )
    return rep.add("shape", PASS, f"parses as {type(doc).__name__}")


def check_tool_load(rep: Report) -> str:
    tool = next((t for t in ("opengrep", "semgrep") if shutil.which(t)), None)
    if tool is None:
        return rep.add(
            "tool_load", UNVALIDATED,
            "neither opengrep nor semgrep is on PATH, so nothing confirmed the tool accepts "
            "this file. UNVALIDATED, not a pass.",
        )
    rc, out = _run([tool, "--validate", "--config", str(rep.path)])
    if rc != 0:
        return rep.add("tool_load", FAIL,
                       f"{tool} --validate exited {rc}: {out.strip()[:400]}")
    counts = [int(m) for m in _RULE_COUNT.findall(out)]
    loaded = max(counts) if counts else None
    if loaded is None:
        return rep.add(
            "tool_load", FAIL,
            f"{tool} --validate exited 0 but reported no loaded-rule count in: "
            f"{out.strip()[:200]!r}. The artifact existing is not evidence the tool "
            "accepted it.",
        )
    if loaded == 0:
        return rep.add("tool_load", FAIL,
                       f"{tool} loaded 0 rules from this file, so nothing would run")
    return rep.add("tool_load", PASS, f"{tool} loaded {loaded} rule(s)")


def check_compiles(rep: Report) -> str:
    suffix = rep.path.suffix
    builder = COMPILERS.get(suffix)
    if builder is None:
        return rep.add("compiles", UNVALIDATED,
                       f"no compile check known for '{suffix or rep.path.name}'")
    cmd = builder(rep.path)
    cwd = None
    if suffix == ".rs":
        cwd = next((p for p in rep.path.parents if (p / "Cargo.toml").is_file()), None)
        if cwd is None:
            return rep.add("compiles", FAIL,
                           f"{rep.path} has no Cargo.toml in any parent, so no fuzz target "
                           "could ever build it")
    if shutil.which(cmd[0]) is None and cmd[0] != sys.executable:
        return rep.add("compiles", UNVALIDATED,
                       f"{cmd[0]} is not on PATH; buildability UNVALIDATED, not a pass")
    rc, out = _run(cmd, cwd=cwd)
    if rc != 0:
        return rep.add(
            "compiles", FAIL,
            f"`{' '.join(cmd[:3])}` exited {rc}: {out.strip()[:400]}. A harness that does "
            "not build is a coverage gap reported as coverage.",
        )
    return rep.add("compiles", PASS, f"`{cmd[0]}` accepted it")


def validate(path: Path, kind: str, normalize: bool) -> Report:
    rep = Report(path, kind)
    if check_exists(rep) == FAIL:
        return rep
    if check_non_empty(rep) == FAIL:
        return rep

    if kind == "rules":
        text = path.read_text(errors="replace")
        check_encoding(rep, normalize)
        text = path.read_text(errors="replace")  # --normalize may have rewritten it
        check_not_commented_out(rep, text)
        check_shape(rep, text)
        check_tool_load(rep)
    elif kind == "json":
        check_json(rep)
    elif kind == "harness":
        check_encoding(rep, normalize)
        check_compiles(rep)
    # corpus: existence and non-emptiness are the whole contract -- a seed input is
    # arbitrary bytes by design, so any shape check here would reject valid corpora.
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="validate-generated.py")
    ap.add_argument("--kind", required=True,
                    choices=["rules", "json", "corpus", "input", "harness"])
    ap.add_argument("path")
    ap.add_argument("--normalize", action="store_true",
                    help="rewrite typographic characters to ASCII in place")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)

    kind = "corpus" if args.kind == "input" else args.kind
    rep = validate(Path(args.path).expanduser(), kind, args.normalize)

    if args.as_json:
        print(json.dumps(rep.as_dict(), indent=2, sort_keys=True))
    else:
        for c in rep.checks:
            print(f"[{c['status']:<11}] {c['check']}: {c['detail']}")
        code = rep.exit_code()
        if code == EXIT_FAIL:
            failed = [c["check"] for c in rep.checks if c["status"] == FAIL]
            print(f"validate-generated: INVALID {rep.path} ({', '.join(failed)}). Nothing "
                  "may depend on this artifact.", file=sys.stderr)
        elif code == EXIT_UNVALIDATED:
            skipped = [c["check"] for c in rep.checks if c["status"] == UNVALIDATED]
            print(f"validate-generated: UNVALIDATED {rep.path} ({', '.join(skipped)}). "
                  "Record it as unverified, never as valid.", file=sys.stderr)
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())

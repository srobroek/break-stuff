#!/usr/bin/env bash
# Pour a sabot campaign molecule and wire the gates that `bd mol pour` leaves unwired.
#
# Verified on bd 1.2.2: a formula's `[steps.gate]` step pours a gate bead attached to the
# molecule root by parent-child alone. It carries no blocking edge, so the approval it
# represents blocks nothing and an autonomous run walks straight past a human gate.
# Ordinary `needs` edges pour correctly as `blocks`, so the gap is specific to gates.
#
# Usage:
#   pour-campaign.sh --run-id run-<id> --target <target> [--var k=v ...]
#
# Exits non-zero when a gate cannot be wired, because a campaign whose approval gate is
# inert is worse than one with no gate at all: the graph asserts an approval that never
# happened.

set -euo pipefail

RUN_ID=""
TARGET=""
EXTRA_VARS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --run-id) RUN_ID="$2"; shift 2 ;;
    --target) TARGET="$2"; shift 2 ;;
    --var) EXTRA_VARS+=("--var" "$2"); shift 2 ;;
    *) echo "pour-campaign: unknown argument $1" >&2; exit 2 ;;
  esac
done

[ -n "$RUN_ID" ] || { echo "pour-campaign: --run-id is required" >&2; exit 2; }
[ -n "$TARGET" ] || { echo "pour-campaign: --target is required" >&2; exit 2; }

command -v bd >/dev/null || { echo "pour-campaign: sabot requires the beads CLI (bd)" >&2; exit 1; }
command -v jq >/dev/null || { echo "pour-campaign: jq is required to read bd --json" >&2; exit 1; }

# Which gate guards which step. The gate's title prefix identifies it, because the pour
# assigns the bead a generic "Gate: human" title and the formula step id is not kept.
#
# A gate is matched to its target by the step number in the formula step's own title, so
# adding a gate to the formula means adding a row here.
GATE_TARGETS=(
  "step 3 gate:step 4 repo-global pre-pass"
  "step 15 gate:step 15 patch"
)

echo "pour-campaign: pouring sabot-campaign for $RUN_ID"
POUR=$(bd mol pour sabot-campaign \
  --var "run_id=$RUN_ID" --var "target=$TARGET" \
  ${EXTRA_VARS[@]+"${EXTRA_VARS[@]}"} 2>&1)
echo "$POUR"

ROOT=$(printf '%s\n' "$POUR" | sed -n 's/.*Root issue: \([A-Za-z0-9-]*\).*/\1/p')
[ -n "$ROOT" ] || { echo "pour-campaign: could not read the root bead id from the pour output" >&2; exit 1; }

BEADS=$(bd list --parent "$ROOT" --json 2>/dev/null)

wired=0
for row in "${GATE_TARGETS[@]}"; do
  gate_prefix="${row%%:*}"
  target_prefix="${row##*:}"

  gate_id=$(printf '%s' "$BEADS" | jq -r --arg p "$gate_prefix" \
    'map(select(.title|startswith($p)))|.[0].id // empty')
  target_id=$(printf '%s' "$BEADS" | jq -r --arg p "$target_prefix" \
    'map(select(.title|startswith($p)))|.[0].id // empty')

  # A gate whose target was filtered out by a condition is not an error: the step it
  # guarded does not exist in this pour, so there is nothing to approve.
  if [ -z "$target_id" ]; then
    echo "pour-campaign: no target for '$gate_prefix' in this pour, skipping"
    continue
  fi
  if [ -z "$gate_id" ]; then
    echo "pour-campaign: no gate bead for '$gate_prefix' in this pour, skipping"
    continue
  fi

  bd dep add "$target_id" "$gate_id" >/dev/null
  echo "pour-campaign: $gate_id now blocks $target_id"
  wired=$((wired + 1))
done

# Assert rather than trust. The whole reason this script exists is a pour that reported
# success while leaving a gate unwired.
failed=0
for row in "${GATE_TARGETS[@]}"; do
  gate_prefix="${row%%:*}"
  target_prefix="${row##*:}"
  target_id=$(printf '%s' "$BEADS" | jq -r --arg p "$target_prefix" \
    'map(select(.title|startswith($p)))|.[0].id // empty')
  gate_id=$(printf '%s' "$BEADS" | jq -r --arg p "$gate_prefix" \
    'map(select(.title|startswith($p)))|.[0].id // empty')
  [ -n "$target_id" ] && [ -n "$gate_id" ] || continue

  if ! bd dep list "$target_id" 2>/dev/null | grep -q "$gate_id"; then
    echo "pour-campaign: FAILED to wire $gate_id -> $target_id" >&2
    failed=$((failed + 1))
  fi
done

if [ "$failed" -gt 0 ]; then
  echo "pour-campaign: $failed gate(s) left unwired; an unwired approval gate blocks nothing" >&2
  exit 1
fi

echo "pour-campaign: $wired gate(s) wired and verified; root $ROOT"
echo "pour-campaign: next step -- bd ready"

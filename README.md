# jackhammer

Offensive and robustness auditing for code, scripts, hooks, and agents.

A blunt-force tool applied to your own codebase until the cracks show: it does
recon to learn what a repo assumes about itself, then attacks those assumptions
across seven surfaces — code, shell/hooks, agents/prompts, infra/supply-chain,
web/frontend, build/toolchain, and robustness — proving each finding with a
reproducing input or a traced path.

## Install

**Claude Code**

```
/plugin marketplace add srobroek/jackhammer
/plugin install break-stuff
```

**APM**

```
apm install srobroek/jackhammer/packages/break-stuff
```

## What it is

`break-stuff` is a skill plus five agents (scout, fuzzer, gremlin, triager,
challenger, hardener) that drive a recon-first campaign: standard scanners and
fuzzers are borrowed as they come, and recon builds the harness that aims them.
Execution runs in a locked-down container. Findings carry two axes — evidence
tier and impact — and are demoted rather than dropped. Advisory by design;
product code is patched only on explicit approval.

Requires the `beads` package (task-graph substrate) and a container runtime
(docker/finch/colima) for the execution phases.

License: Apache-2.0

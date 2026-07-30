# Interview: pin the scope before the campaign spends a token

The campaign is only as good as its scope. A wrong target, an unstated surface, or
an unapproved budget wastes the whole run, so the interview exists to remove every
ambiguity that would change what gets attacked or how much it costs.

This is not a script to read out. It is a set of facts that MUST be certain before
step 4, and a way to probe for them that adapts to what the user already said. A
user who names a PR and a threat has answered half of it in one sentence; a user
who says "check my repo" has answered none of it. Ask for what is still unknown,
not for what was already given.

## What MUST be certain before recon

Ask the interview in two separate parts. A **core** every run asks pins what to
attack and how much; a **blast-radius opt-in**, asked only when a triggering surface
is in scope, authorizes the few actions that run real payloads through real grants.
Do not fold the opt-in into the core questions, and never present an action the hard
rules forbid.

### Core (always asked, the three STOP questions)

| Fact | STOP question | Why it changes the run | Unpins the run when |
|---|---|---|---|
| Target | 1 | decides the file list and the base ref | "the repo" without a kind, since scanning the whole repo is a choice the user has to make deliberately |
| User's threat | 1 | what the user fears decides which surface leads and orders the report | absent: the report prioritizes nothing |
| Surfaces | 2 | each surface is a parallel gremlin and a cost | detected set never shown to the user to trim or extend |
| Tools + budget | 3 | decides coverage and wall-clock, and bounds the machine | "go" on an unseen tool set, or a budget the user never approved |

MUST Resolve the core four before spawning a scout. A campaign that starts under an unpinned scope produces findings for the wrong target and a coverage claim it cannot support.
MUST Record every defaulted fact as a gap in the report. "Whole repo, because none was named" belongs there, since the user may have meant one module.

### Blast-radius opt-in (a SEPARATE question, only when applicable)

Live-spawn agentic fuzzing and dev-server DAST run real payloads through real grants,
so they are OFF by default and each is a distinct opt-in the user names, asked AFTER
the core is pinned, and only when its triggering surface was detected. When the
trigger is absent, the option does not exist for this run: do not list it, not even
as "N/A" or "unavailable", since a greyed-out option frames a non-choice as a dial.

| Opt-in | Asked only when | If declined or not triggered |
|---|---|---|
| Live-spawn agentic fuzzing | agent/skill/MCP definitions are in scope AND the user opts in | omitted from the question entirely; the definition-review pass still runs statically |
| Dev-server DAST | a runnable web server is in scope AND the user opts in | omitted entirely; the static web pass still runs |
| LLM access for grading | live-spawn or promptfoo grading was opted into | agentic-fuzz is skipped, recorded as a declined opt-in |

MUST Ask each blast-radius opt-in as its own question after the core, and only when its triggering surface is in scope. An opt-in offered with no trigger is clutter; an opt-in folded into the core question buries the consent that matters.
MUST Omit entirely any action the hard rules forbid (attacking a network host, a public endpoint, or a third-party service). It is never a menu option, an "N/A" row, or an "unavailable" line. A referenced-but-forbidden target (a CI file that probes a live host) is read statically and not mentioned in the interview at all.
MUST Restate what a granted opt-in will run, against what, before the first spawn, and wait. An offhand "sure" is not the authorization a live-spawn or DAST run requires.
MUST Ask, when the user opts into agentic grading (promptfoo or live-spawn), which LLM to use: an API key with its provider, a local or self-hosted endpoint, or none (which skips agentic-fuzz). Grading runs host-side, since the agents surface is container-free, so the credential stays a plain host env var and is never baked into an image. Keep this question inside the opt-in block, out of the core.

## How to probe: adapt, do not recite

Run the interview as a loop. Read what the user gave, restate your current
understanding, and ask only for the gap that most changes the run. Stop the moment
the five facts are certain, since an extra question on a scope already pinned is
friction the user reads as indecision.

MUST Restate the resolved scope in one block before recon: target kind, file count, threat, surfaces, base ref, checkout, budget, and every default applied. A scope the user did not intend is caught here or not at all.
MUST Ask the question that resolves the most unknowns first, then re-read. The answer often settles two others, so a fixed order asks questions the last answer already closed.
MUST Prefer a concrete menu over an open question when the axis is closed. "Whole repo, this module, or the diff on your branch?" resolves faster than "what do you want to scan?", because the user recognizes the right answer rather than composing it.
NOT Never batch all five into one wall of questions. A user faced with a form answers the easy ones and skips the one that mattered.

## Reading the answers: what to distrust

An answer can pin a fact and hide a landmine. Probe further when:

| The user says | Distrust because | Probe |
|---|---|---|
| "scan everything" | whole-repo on a large tree is hours of budget and a flooded report | offer the diff or the module they actually changed; confirm they want the whole tree |
| "just check for vulnerabilities" | no threat model means no prioritization | ask which failure would hurt worst, so the answer names a surface rather than the whole repo |
| "it's fine, go" on an unseen tool set | a declined tool is a silent coverage gap they never saw | show the default-on set and the cost once, then accept "go" |
| "yes, fuzz the agents live" | live-spawn runs real payloads through real tool grants | confirm the exact targets, the lease, and the case count before the first spawn |
| "the whole thing is untrusted input" | everything-is-tainted maps no boundary | ask where trusted and untrusted actually meet, naming the concrete edge (an HTTP handler, a CLI argument, a file read, an env var) |
| a target with no ref | a clean tree still has a mergeable change to audit | offer commit / range / branch / PR, since a regression review is a different question |

MUST Convert a vague fear into a falsifiable scope. "I want it secure" becomes "attacker-controlled input must never reach the shell in `hooks/`", which names a surface and a boundary recon can then map.
MUST Treat an offhand "yes, fuzz it live" as a cue to open the blast-radius opt-in properly, not as the approval itself. Route it to that separate question (above), restate what will run and against what, and wait.

## When there is no one to ask

A non-interactive run (CI, a cron job, a sub-agent with no user) cannot interview.
It does not therefore guess: it takes the deterministic defaults and records each as
a gap, so the report states the scope it assumed rather than implying the user chose
it.

| Fact | Non-interactive default |
|---|---|
| Target | the target passed in the spawn, else the whole repo |
| Threat model | none; every surface is treated at equal priority and the report says so |
| Surfaces | the full detected set, robustness always included |
| Tools + budget | the installed tools and the `fuzzing.md` budget defaults |
| Blast-radius | live-spawn and DAST are OFF; they require an interactive opt-in |

MUST Refuse live-spawn and dev-server DAST in a non-interactive run. Both need a target the user named and an explicit human authorization that a defaulted run cannot supply.
MUST Record every default as a coverage gap. A non-interactive run that hides its assumptions reads as a scoped audit when it was a whole-repo sweep on borrowed defaults.

## Handing the scope forward

The interview feeds step 1 (open the run) and step 2 (resolve the target). Stamp the
resolved scope on the run epic so a resumed campaign reuses it rather than
re-interviewing. The target kind and base ref flow into `targeting.md`; the surfaces
and budget become the surface nodes and the epic's `budget` metadata.

The user's stated threat is stamped on the epic as `threat` metadata, where it
orders the report and ranks which surface leads. Keep it out of the scout Brief. A
scout told where the bug is stops censusing, so recon derives the repo's own threat
model independently (see `recon.md` and `scout-brief.md`). The user's fear
prioritizes attention; the derived model is the map recon builds without a
hypothesis.

MUST Stamp the user's threat on the epic for prioritization and reporting, and keep it out of the scout Brief. A scout handed a suspected bug narrows its census to that guess and misses the deviations that census exists to find.

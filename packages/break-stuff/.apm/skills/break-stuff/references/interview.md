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

Every campaign needs these five resolved. Until each is either answered or
defaulted-with-a-recorded-gap, the scope is not pinned.

| Fact | Why it changes the run | Unpins the run when |
|---|---|---|
| Target | decides the file list and the base ref | "the repo" without a kind, since scanning the whole repo is a choice the user has to make deliberately |
| Threat model | what the user fears decides which surface leads | absent: the run attacks everything equally and prioritizes nothing |
| Surfaces | each surface is a parallel gremlin and a cost | detected set never shown to the user to trim or extend |
| Tools + budget | decides coverage and wall-clock, and bounds the machine | "go" on an unseen tool set, or a budget the user never approved |
| Blast-radius consent | live-spawn and DAST run real payloads through real grants | live-spawn or a dev-server scan assumed rather than authorized |

MUST Resolve all five before spawning a scout. A campaign that starts under an unpinned scope produces findings for the wrong target and a coverage claim it cannot support.
MUST Record every defaulted fact as a gap in the report. "Whole repo, because none was named" belongs there, since the user may have meant one module.

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
MUST Escalate the blast-radius questions to their own explicit gate. Live-spawn and DAST are the most invasive things the skill does, so an offhand "sure" is not the approval they require. Restate what will run and against what, then wait.

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

The interview's output is the input to step 1 (open the run) and step 2 (resolve the
target). Stamp the resolved scope on the run epic so a resumed campaign reuses it
rather than re-interviewing:

- target kind + resolved file list + base ref + checkout decision → `targeting.md`
- threat model in one falsifiable line → carried into every scout Brief as the aim
- surfaces + budget → the surface nodes and the epic's `budget` metadata

MUST Stamp the threat model on the epic, since it is what aims recon and a scout without it censuses everything and prioritizes nothing.

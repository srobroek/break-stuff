# Escalation and attack-vector baselines: build them, do not look them up

A checklist finds one bug at a time. The findings that matter chain, where a
low-severity primitive plus a second reaches an impact neither has alone. This
file teaches how to construct those chains and derive a per-repo attack-vector
baseline. It ships no vector list, since a shipped list is one the author already
defended against. The vectors worth writing are the ones this codebase's structure
creates, which only recon can find.

Read this after `recon.md`, whose trust map, invariant list, and idiom census are
the raw material every construction below consumes.

## Why nothing here is static

A fixed vector catalogue rots the moment it ships. The author reads it, closes those
holes, and the catalogue now measures nothing while reading like coverage. What
lasts is the method for turning *this* repo's trust map into *this* repo's attack
tree, which a bigger catalogue never becomes.

MUST Derive every vector from recon's artifacts. A vector that could have been written without reading this repo tests a generic weakness the author already knows about.
MUST Treat a generic pattern as a starting question. "SQL injection" is a class; the vector is "the one handler in `orders/` that interpolates while the other 40 parameterize", which only the idiom census names.
NOT Never present a catalogue vector as a finding. Until recon places it on a real path in this repo, it is a hypothesis, and the report tiers it HARDENING.

## Building the attack-vector baseline for a run

The baseline is the set of entry points worth attacking, each paired with the vector
class its shape and position invite. It is constructed per run, from recon, before
any harness is written.

1. **Start from the trust map, not the sink.** Every boundary recon recorded is a
   candidate: data crosses from less-trusted to more-trusted there. The vector is
   whatever violates what the code assumes holds after the boundary.
2. **Pair each boundary with the class its shape invites.** A boundary parsing bytes
   invites malformed-input and resource vectors; one building a command invites
   injection; one deciding authorization invites a bypass; one reading a length field
   invites overflow and unbounded allocation. The surface doc's attack checklist is
   the menu of classes, and the baseline is which class each *specific* boundary earns.
3. **Rank by the assumption's blast radius.** A boundary whose post-condition, if
   false, reaches a shell or a write outranks one whose failure is a wrong log line.
   Recon already recorded what each boundary assumes; rank by what breaks when the
   assumption does.
4. **Fold in the idiom deviations.** Each place the census found that departs from
   the repo's own pattern is a baseline vector on its own, because the deviation is
   where the shared defense is absent.

MUST Build the baseline from recon's boundaries and deviations, so every vector traces to a `file:line` in this repo rather than to a class name.
MUST Rank baseline vectors by the blast radius of the assumption each one breaks, since the budget is finite and the highest-radius boundary is where a proven finding pays for the run.
MUST Hand the baseline to the fuzzer as its work list. A fuzzer given ranked, boundary-anchored vectors writes harnesses that reach real logic; one given a class list writes never-panics harnesses and nothing else.

## Constructing an escalation chain

A chain turns two cheap primitives into one expensive impact. Construct it by
walking recon's own graph rather than pattern-matching a known CVE shape.

For each primitive a finding grants, ask what the trust map says that primitive can
now reach. When reaching it grants a second primitive, the two chain. Repeat until
the chain hits an impact worth reporting or runs out of reach.

| Primitive a finding grants | Ask the trust map | Chains when |
|---|---|---|
| Read a path the caller chose | what does the code read that later decides a branch or a grant | a read reaches a file that gates authorization or configures a sink |
| Write a path the caller chose | what does the code later read from where this can write | a write lands where a trusted config, a hook, or a corpus is later read |
| Crash or hang one component | what does the caller do when that component is down | a fail-open path, a retry storm, or a degraded mode that skips a check |
| Control one field of a parsed structure | what downstream operation trusts that field | a length drives an allocation, a name drives a path, a flag drives a branch |
| Land content in a durable store | who reads that store later, and with what trust | a later session or agent treats the planted content as its own truth |
| Influence one agent's output | who parses that output, and does the format let it forge control | a caller parses a verdict line the output can forge |

MUST Construct a chain by following recon's trust map from each primitive to what it reaches, rather than matching the finding to an exploit. The chain that matters here is the one this repo's wiring permits, which no external template knows.
MUST File the chain as its own additional finding tiered at the endpoint impact, citing the constituent findings by id. The constituents keep their own rows and tiers under the no-delete rule; the chain sits above them. Two MEDIUM primitives that chain to code execution surface as a CRITICAL the separate rows would hide.
MUST Name every link with a `file:line` and the primitive it grants, so the challenger can test each hop rather than the assertion that they connect.
NOT Never assert a chain you did not trace hop by hop. "These could combine" without the intermediate reach stays a HARDENING note until the reach is shown.

## Availability as an escalation axis

Denial of service is an impact a chain can reach, not only a crash class. A primitive
that exhausts a resource or wedges a component escalates when the trust map shows a
consequence downstream of the outage. Treat availability the same way: start from
what the finding lets an attacker exhaust or stall, then ask what the code does when
that happens.

| Availability primitive | Escalates when the trust map shows |
|---|---|
| Unbounded allocation from one input | the process is shared, so one caller's input degrades every caller |
| Superlinear work (ReDoS, quadratic parse) | the work runs on a request path with no upstream time or size cap |
| A crash on the hot path | a supervisor restarts into the same input, or a fail-open path opens on the outage |
| Lock or resource never released | a second request blocks forever, turning one bad input into a wedge |
| Fork or spawn without a ceiling | the input sets the count with no limit above it (fuzz the code that reads the count; never author a harness that actually spawns them, per the authoring ban) |

MUST Judge an availability finding by what the outage reaches, not by the crash alone. A panic on a local dev tool is LOW; the same panic on a shared request path where a supervisor re-feeds the input is a sustained outage.
MUST Fuzz the code path that RECEIVES the exhausting input, never author a harness that performs the exhaustion. The finding is that the target accepts an input that would exhaust, per the authoring ban in `isolation.md`.

## Handing escalation forward

- The **baseline** is fuzzer input: ranked, boundary-anchored vectors, filed as the
  fuzzer's work list on the run epic.
- A **chain** is a challenger concern: the gremlin files each primitive as its own
  finding wisp with its `file:line`, and the challenger tests whether the hops
  connect and stamps the chain at its endpoint impact.

MUST File each link of a chain as its own wisp, then let the challenger tier the chain, since the writer-executor-judge split forbids the finder from asserting its own escalation.

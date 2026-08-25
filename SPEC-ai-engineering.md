# ai-router — AI engineering spec

Written 2026-08-25. What is missing from the routing itself, and the fixes, in
the order they unblock each other.

Scope is the model layer only. Security and reliability gaps are covered in
`consoleDesk/SPEC-desk-ai.md` §7–§8 and are not repeated here.

---

## The headline

**This is a cost router with no cost model.**

There is no per-model price table anywhere in the codebase. There is one
constant:

```python
# telemetry_roi.py:31
ANTHROPIC_INPUT_PRICE_PER_M = 3.00
```

applied uniformly to every model. The router selects among Opus, Sonnet, Haiku,
Gemini Flash, Gemini Pro and o3-mini — roughly two orders of magnitude apart in
price — and has no representation of what any of them cost.

Every routing decision the tool makes is blind to the quantity it exists to
optimize. Everything below is downstream of that.

---

## 0 — The governing objective

**Quality first, then cost.** Ratified by Leo, 2026-08-25, resolving what was
open decision #4.

This is a *lexicographic* ordering, not a weighted tradeoff, and the distinction
decides most of the architecture below:

> Minimize cost **subject to** quality ≥ threshold.
> Not: maximize quality per dollar.

Read strictly, that means the router never accepts a worse answer in exchange
for a saving, however large. Cost is the tiebreaker **among options that all
clear the bar**, never a reason to drop below it. A 40x price difference does
not justify a model that might not do the job.

Three consequences, each of which reverses something this codebase currently
does or something the previous draft of this spec recommended:

1. **Cheap-first cascade is the wrong pattern.** FrugalGPT-style try-cheap →
   escalate is a *cost-first* architecture: it accepts that some fraction of
   requests get a bad cheap answer, then repairs them. Under quality-first the
   user experiences that failure and pays the latency twice. See the revised A4.
2. **Ambiguity routes up, not down.** Every uncertain classification resolves to
   the stronger model. This makes A6 (confidence gating) load-bearing rather
   than optional, and it means a fabricated confidence constant is now a
   correctness bug, not just dead code.
3. **Silent successes become the top-severity defect.** A8 — a safety-blocked
   empty response reported as `status=success` — is a direct violation of the
   governing objective, not a reporting nuisance.

The cost work in A1–A3 keeps all of its value. Its role changes: it exists to
choose *among adequate models* and to report honestly, not to justify accepting
worse output.

---

## What to expect

| | |
|---|---|
| **A13 is the urgent one** | The fast path bypasses classification entirely and routes on a regex. Under quality-first it is the largest active hazard. |
| **A1–A3 are prerequisites** | Cost model, real token counts, caching. Nothing else can be measured until these land. |
| **A4 is the architecture** | Rewritten under §0: conservative predictive routing, not cheap-first cascade. |
| **A5–A6 are honesty** | The eval measures self-agreement, and confidence is a hardcoded constant now doing load-bearing work. |
| **A10 is free** | An advertised feature that never runs. Delete the claim or wire the function. |

Confidence: high on every finding — each was executed, not read. See §14.

---

## A1 — No cost model

**Missing.** No price table. `ANTHROPIC_INPUT_PRICE_PER_M = 3.00` is the whole
economic model, and it is applied to Gemini and OpenAI routes as readily as to
Anthropic ones. Output tokens are priced at zero everywhere except a lone
hardcoded pair in `codex_engine.py:140`.

**Why it matters.** "Route to the cheapest adequate model" is the product
thesis. A router that cannot compare two models' prices cannot implement it —
it is pattern-matching keywords to model names and calling the result an
optimization.

**Fix.**

```python
# prices.py — input/output USD per 1M tokens, keyed by model id
PRICES = {
    "claude-opus-5":  Price(inp=..., out=...),
    "claude-haiku-4-5-20251001": Price(inp=..., out=...),
    "gemini-2.5-flash": ..., "gemini-2.5-pro": ..., "o3-mini": ...,
}
```

Populate from the providers' current published pricing at implementation time
rather than from memory, and pin a `retrieved` date next to the table — these
change, and a stale table is a silently wrong one. Then:

- `ExecutionResult.cost_usd` computed from real usage, per model.
- Classification becomes cost-aware: the decision is expected quality per
  dollar, not a keyword match.
- `ai roi` reports realized spend against a counterfactual (all-Opus), which is
  the number the tool's name promises.

---

## A2 — No tokenizer

**Missing.** Every token count in the codebase is a whitespace word count:

```python
# claude_engine.py:109
input_tokens = max(10, len(assembled_prompt.split()))
```

**Why it matters.** The README's stated purpose is preventing "context-window
exhaustion". Nothing measures the assembled prompt against any model's context
window. `n8n_max_tokens=1500` caps research context only; `repo_context +
research + task` is never measured as a whole. The headline claim is not
implemented, and every cost figure derives from a number that is not tokens.

**Fix.** A real tokenizer per provider family. Measure the assembled payload
before dispatch. On overflow, either truncate the lowest-value section
(research before repo context before task) or upgrade to a larger-context model
— that second option is a legitimate reason to route *up*, which the router
currently has no concept of. Prefer provider-reported usage over local counting
wherever the response returns it.

---

## A3 — No prompt caching

**Missing.** `grep -rn "cache_control\|ephemeral"` returns nothing.

**Why it matters.** This is the largest single cost lever available and it is
entirely unused. The system instruction and repo context are stable across
calls and near-perfectly cacheable. Cloudflare AI Gateway caching, which the
codebase does implement, is exact-match *response* caching — a different
mechanism that only helps on identical repeated prompts, and it is disabled.

**Fix.** Mark the stable prefix cacheable and order the payload
cacheable-prefix-first. Note the tension: the Claude Code subprocess engine does
not expose this. It argues for an API-based Anthropic engine alongside the CLI
engine — CLI for interactive handoff, API for programmatic calls where caching,
real usage numbers and retries are all available. The facade added in `f744977`
is what makes that second engine straightforward.

---

## A4 — No quality gate, and no safe way down

**Revised under §0.** An earlier draft of this spec recommended a FrugalGPT-style
cheap-first cascade. Quality-first rules that out as the primary mechanism.

**Missing.** The router picks one model and returns whatever comes back. There is
no adequacy check of any kind, and no path from a failed attempt to a stronger
model.

**Why it matters.** Routing down without a gate is not cost optimization — it is
quality degradation with extra steps. But the obvious repair is also wrong here:
try-cheap → score → escalate accepts a bad first answer as the normal case,
which under §0 is precisely what must not happen. The user sees the failure and
waits twice.

**Fix — conservative predictive routing, with cascade only where failure is
invisible.**

1. **Route up on uncertainty.** The default resolution of any ambiguous
   classification is the stronger model. Cheap models are selected only when the
   task is confidently within their envelope — which requires A6 to be real.
2. **Pre-dispatch structural gates, not post-hoc judging.** Before accepting a
   cheap route, check the things that predict failure cheaply and
   deterministically: scope of the request, blast radius, whether the target is
   sensitive, context size. See A13 — this is exactly what the fast path skips.
3. **Cascade only on detectable, pre-delivery failure.** Empty output, truncated
   output, refusal, a `finishReason` other than a normal stop, or a missing
   required artifact. These are detectable before the user sees anything, so the
   retry is invisible and quality-first is preserved. Escalate silently, and
   record the escalation.
4. **Never cascade on "the answer might be weak."** That judgment needs a model
   strong enough that you should have used it first.

Escalation rate stays a first-class metric, but its meaning inverts: under
quality-first a *high* escalation rate means the predictive router is routing
down too aggressively and should be tuned to be more conservative — not that
the cascade is working.

Cascade depth is capped and the cap interacts with the spend ceiling
(`SPEC-desk-ai.md` S4). Note the tension §0 creates: when the ceiling is reached
mid-cascade, quality-first says finish the escalation and cost-second says stop.
The ceiling wins, because an unbounded spend is its own failure — but the router
must then say plainly that it returned a lower-tier answer, rather than
presenting it as final.

---

## A5 — The eval is a tautology

**Missing.** `EvalHarness` runs 8 hand-written cases whose expected labels were
authored alongside the heuristics under test, and reports 100%.

**Why it matters.** Two separate problems. It measures self-agreement — the
heuristics reproduce the labels someone wrote to describe the heuristics. And it
scores *label match*, never *outcome*: nothing anywhere asks whether the cheap
model actually completed the task. A routing decision can be "correct" by this
eval and produce an unusable answer.

**Fix.** Sample real traffic from `~/.ai_router/audit.log`, which already
records intent, engine, model, effort, duration and exit code per call. Hold out
a labeled set. Change the metric from classification accuracy to **cost per
successful task**, with escalation rate and p50/p95 latency reported alongside.
Keep the 8 synthetic cases as a smoke test and stop calling the result accuracy.

---

## A6 — Confidence is fabricated

**Missing.** `ClassificationResult.confidence` is a hardcoded constant per code
path — `0.99` on the fast path, `0.95` from Gemini, `0.90` from the heuristic.
It is never derived and never read.

**Why it matters.** A dead field that looks like a signal. The natural use —
route ambiguous cases to the safer model — is exactly what a cost router should
do, and the field's presence suggests it happens.

**Fix.** Derive it (self-consistency across samples, or logprobs where
available) and gate on it: below threshold, skip the cheap tier. Or delete the
field. Leaving a fabricated confidence score in a routing decision is the worst
of the three options.

---

## A7 — Silent classifier degradation

**Missing.** `classifier.py:78` — `except Exception: pass`, then fall through to
the regex heuristic. Nothing is logged, counted or surfaced.

**Why it matters.** The install is in this state right now. `GEMINI_API_KEY` is
unset, so `ai doctor` reports a WARN and every classification is keyword
matching. The product's premise is model-based routing; it is currently regex,
and only a diagnostic subcommand hints at it.

**Fix.** Count fallbacks, log the exception class, surface the silent-fallback
rate in `doctor` and `roi`. The fallback itself is good engineering and should
stay — a router that hard-fails when its classifier is down is worse. What is
wrong is that the degradation is invisible.

---

## A8 — Two silent successes

**Missing.** Verified by execution:

```
gemini engine, empty stream (safety block / refusal):
  status=success  exit=0  output=''  error=None
```

An empty stream — which is what a safety block, a refusal, or a `finishReason`
other than `STOP` produces — is reported as a successful run with no output.
Telemetry counts it as a completed command. The same shape exists on the Codex
path.

**Why it matters.** Silent success is the worst failure mode in a routing
system, because it corrupts the very metrics that would reveal it. Cheap models
refuse more often than expensive ones, so this bias flatters exactly the
decisions the router is most likely to get wrong.

**Fix.** Empty output with no error is a failure. Parse `finishReason` and
`promptFeedback` (Gemini) and `finish_reason` (OpenAI); map safety stops,
length stops and refusals to distinct statuses. Exclude them from success
telemetry.

---

## A9 — No retry, no failover

**Missing.** No retry, backoff or jitter anywhere. HTTP engines set a 60s
timeout and give up on first error. `--fallback-model`, which the Claude CLI
supports, is unused.

**Why it matters.** 429s and overload responses are routine on all three
providers. And the tool already holds the thing that makes failover trivial —
three configured providers — using them for routing but never for resilience.

**Fix.** Retry with exponential backoff and jitter on 429/5xx/overload. On
exhaustion, fail over to the next provider at equivalent tier, and record the
substitution in `RouteResult` so the cost attribution stays honest. Wire
`--fallback-model` on the CLI path.

---

## A10 — Advertised dedup never runs

**Missing.** `ContextPruner`'s docstring: "Computes Jaccard/lexical similarity
between scraped docs and local repo context. Strips redundant paragraphs."

`compute_jaccard_similarity` is called by nothing but its own unit test.
`prune_and_budget` never invokes it. `seen_signatures` is assigned and never
read. The deduplication does not happen.

**Why it matters.** Small in cost terms, larger in trust terms: a documented
feature with a passing test that is not wired into the path it claims to serve.

**Fix.** Wire it — prune research paragraphs above a similarity threshold
against `repo_context`, which is the stated design and a real token saving — or
delete the function and the docstring claim.

---

## A11 — Effort is prose on one path only

**Missing.** The Claude engine injects reasoning effort as text:

```xml
<effort_budget level="5">Apply maximum exhaustive verification…</effort_budget>
```

Gemini's `thinkingConfig.thinking_budget` and OpenAI's `reasoning_effort` are
wired as real API parameters. Only the Anthropic path substitutes prompt
steering for a control surface.

**Why it matters.** Prompt-level steering and a reasoning-budget parameter are
not equivalent, and the asymmetry means "effort 5" means three different things
depending on which engine ran. Any cross-engine comparison is invalid.

**Fix.** Use the real control where one exists on each path. Where it does not,
say so in `RouteResult` rather than reporting a number that implies parity.

---

## A12 — Classification is not cached

**Missing.** Identical prompts are reclassified on every invocation.

**Fix.** Hash the prompt plus repo fingerprint; cache the classification beside
the existing session cache. Cheap, and it directly reduces the
classify-call-to-save-a-call overhead that makes routing uneconomic on short
prompts.

---

## A13 — The fast path is scope-blind

**Found 2026-08-25, after §0 was ratified. Under quality-first this is the
largest active hazard in the router.**

`IntentClassifier.FAST_EXECUTE_PATTERNS` matches a verb-and-noun prefix and
routes straight to the cheapest model at the lowest effort, **before any model
sees the prompt**. It reads the first few words and discards the rest. Executed:

| Prompt | Routes to |
|---|---|
| `Fix typo in README.md` | `claude-haiku-4-5`, effort 1 |
| `Fix syntax across the entire auth module` | `claude-haiku-4-5`, effort 1 |
| `Fix lint in the payment reconciliation service` | `claude-haiku-4-5`, effort 1 |
| `correct spelling in the PPM offering document` | `claude-haiku-4-5`, effort 1 |
| `remove unused code from the crypto signing path` | `claude-haiku-4-5`, effort 1 |
| `git commit the migration that drops the users table` | `claude-haiku-4-5`, effort 1 |
| `rename function verifyWebhookSignature everywhere` | `claude-haiku-4-5`, effort 1 |

Only the first is a genuine fast-path task. Every other row names a scope the
regex never looks at — "across the entire auth module", "the crypto signing
path", "drops the users table", "everywhere" — and one of them is a destructive
git operation dispatched to the weakest model at minimum effort.

**Why it matters.** This cannot be fixed by improving classification, because
the fast path exists to *skip* classification. It is a 5ms optimization that
buys latency by discarding the information needed to route safely, and it sits
upstream of every other quality control in this document. Under §0 it is a
direct violation: it routes down on no evidence at all.

The counsel-gate case is worth stating separately. `correct spelling in the PPM
offering document` sends Reg D offering material to the cheapest model at the
lowest effort on the strength of the word "correct".

**Fix.**

1. **Scope guards on every fast-path match.** Reject the fast path when the
   prompt names breadth (`all`, `every`, `everywhere`, `across`, `entire`,
   `codebase`, `module`, `service`), sensitivity (paths or nouns on a
   sensitive list — auth, crypto, signing, payment, migration, PPM, offering),
   or destructive verbs (`drop`, `delete`, `rm`, `truncate`, `force`, `reset`).
   Any hit falls through to full classification rather than routing cheap.
2. **Bound it by length.** A genuine fast-path task is short. A prompt past a
   modest word count is not a typo fix regardless of how it opens.
3. **Never fast-path a `git` command with side effects.** The current
   `^git\s+(status|diff|add|commit|push|checkout|branch)` pattern mixes
   read-only verbs with `commit`, `push` and `checkout`. Split it: read-only
   verbs may fast-path, the rest may not.
4. **Log every fast-path decision** so the false-positive rate is measurable
   rather than assumed. This is the cheapest input to the A5 eval.

---

## Build order

Each stage unblocks the next; the order is not arbitrary.

**Stage 0 — stop routing down on no evidence.** A13 scope guards. Promoted to
first under §0: it is live, it is upstream of every other control here, and it
is the one gap actively producing bad routes today. Days, not weeks.

**Stage 1 — stop lying.** A8 silent successes, A7 classifier visibility, A10
dead dedup. Promoted above the cost work: under quality-first, a failure
reported as a success is the worst defect in the system, and all three corrupt
the metrics Stage 2 is about to make real.

**Stage 2 — make it measurable.** A1 price table, A2 tokenizer. Nothing
downstream can be evaluated until a call has a real cost and a real token count.

**Stage 3 — take the free money.** A3 prompt caching, A12 classification cache.
Largest cost reduction per unit of work, independent of the routing logic, and
free of any quality tradeoff — which is exactly why it is the cost work that
survives §0 untouched.

**Stage 4 — the architecture.** A6 real confidence, then A4 conservative
predictive routing. In that order: routing up on uncertainty is meaningless
while confidence is a hardcoded constant.

**Stage 5 — harden and prove.** A9 retry and failover, A11 effort parity, A5
outcome-based eval on real traffic. The eval goes last because it needs
everything above it to measure anything meaningful.

The reordering against the previous draft is entirely a consequence of §0.
Cost-first would have run Stage 2 before Stage 1; quality-first will not measure
savings on a telemetry layer that counts refusals as wins.

---

## Open decisions

1. **Does an API-based Anthropic engine get built alongside the CLI engine?**
   A3, A9 and real usage numbers all need it; the Claude Code subprocess exposes
   none of them. Recommendation: yes — CLI engine for interactive handoff, API
   engine for programmatic calls.
2. **What is the adequacy signal in the cascade?** A cheap model judging a cheap
   model is weak; a strong model judging is expensive enough to erase the saving.
   Recommendation: start with cheap structural checks — empty, truncated,
   refused, failed to produce required artifacts — before reaching for a judge
   model.
3. **Is `confidence` derived or deleted?** Both defensible. Leaving a hardcoded
   constant in a routing decision is not.
4. ~~**Does the router optimize cost, latency, or quality?**~~ **Resolved
   2026-08-25: quality first, then cost.** See §0. Latency is explicitly not in
   the ordering, which is itself a decision — it is why A4 permits invisible
   pre-delivery retries but not user-visible ones.

5. **Where is the quality threshold set, and by whom?** §0 makes the router
   minimize cost subject to quality ≥ threshold, but nothing yet defines the
   threshold. It cannot be a single global number — a typo fix and a migration
   do not deserve the same bar. Recommendation: per-intent floors, with the
   sensitive-path list from A13 forcing the top tier regardless of intent.

---

## How these findings were verified

Executed, not read. All on 2026-08-25 against `f744977`.

| Finding | Method | Result |
|---|---|---|
| A1 no price table | `grep -rniE "price\|cost_per\|per_m\|usd_per"` | one constant, `telemetry_roi.py:31` |
| A2 word counts | read `claude_engine.py:109,154` | `len(prompt.split())` |
| A3 no caching | `grep -rniE "cache_control\|ephemeral"` | no matches |
| A7 silent fallback | `ai doctor` | `GEMINI_API_KEY` empty, heuristic active |
| A8 silent success | ran Gemini engine against an empty stream | `status=success exit=0 output=''` |
| A9 no retry | `grep -rniE "retry\|backoff\|max_retries\|tenacity"` | no matches |
| A10 dead dedup | `grep -rn "compute_jaccard_similarity"` | definition + its own test only |
| A11 effort as prose | stub binary captured real argv | `<effort_budget>` in the prompt text |
| `--fallback-model` unused | `claude --help`; `grep` the codebase | flag exists, never passed |
| A13 scope-blind fast path | ran 8 prompts through `IntentClassifier.evaluate` | all 8 → `claude-haiku-4-5`, effort 1, `is_fast_path=True` |

The telemetry distortion that motivates A1 and A5 is recorded separately in
`consoleDesk/SPEC-desk-ai.md` §8 E2: 34 Cloudflare edge cache hits recorded with
no gateway configured, from a hardcoded value in `mock_services.py:113`.

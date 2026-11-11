# NeMo Relay sandbox lab — findings (2026-11-10)

Setup: `nemo-relay` 0.11.1 (PyPI) in an isolated venv on macOS arm64. Offline mock model/tool
callbacks; no API keys and no company traffic. Plugins: observability (ATOF + ATIF) and
pii_redaction (email + credit_card). Scripts: `scripts/fleet_lab.py`, `scripts/overhead.py`.
Runs: `runs/01-quickstart` … `runs/05-overhead`.

Context: the fleet design follows NVIDIA's livestream "Inside Hermes Agent Traces with NeMo Relay", where
Nous Research described four observability levels (L1 health, L2 analytics without content, L3 audit, L4 full
trajectories) and fencing personal agents to L2 in its OpenTelemetry collector. "Victor" and "Patrick" below
refer to speakers on that livestream; their points are paraphrased from the auto-generated transcript.

## Findings

1. **The quickstart on `main` doesn't install.** It pins `nemo-relay==1.0.0`; PyPI's latest is 0.11.1.
2. **"Full payloads off" still captures content.** With `enable_full_payloads = false`, ATOF still
   holds the prompt, response, tool args and tool results. The flag only turns off repeating
   earlier turns.
3. **Relay injects `x-dynamo-session-id`** into outgoing model requests by default (a link to the
   NVIDIA Dynamo inference stack).
4. **Per-agent privacy tiers are possible but must be hand-built.** Scope-local sanitizers and
   metadata injectors on the personal agent's scope made its whole subtree (including its subagent)
   content-free while the shared agent kept full content. The context propagated correctly to all
   descendants.
5. **Content and analytics share the same fields.** Token usage lives in `data.usage` (the raw
   response) and in `category_profile.annotated_response`, next to the message text. Fence v1 kept
   `category_profile` and leaked prompts into ATIF `extra.observed_events`. Fence v2 had to keep
   only `usage`, `model_name` and `finish_reason` by hand.
6. **A content-free agent is nearly invisible in ATIF.** With fence v2 the personal trajectory went
   from 3 steps to 1, and `final_metrics` lost its token totals, because ATIF derives them from the
   stripped annotations.
7. **Without a response codec, token counts exist only in raw content.** Dropping `data` drops
   tokens, so the opt-in codec decides whether L2 analytics are possible.
8. **The root agent's own start event can't carry injected context.** The injector registers after
   the scope opens; only `metadata=` at creation reaches that first event.
9. **Blocked calls are auditable as "blocked" but not as "what was attempted."** The rejection mark
   has the reason; the attempted args (`rm -rf /data/archive`) appear nowhere. That protects
   privacy but leaves an audit gap. The guardrail check itself is recorded as its own `guardrail`
   scope, which is good.
10. **Regex PII redaction is narrow.** Email and card numbers were redacted; the phone number
    (detector not enabled) and the name in "bob smith card dispute" passed through. Formatting slip:
    `card [REDACTED]and call me` (the trailing space was consumed).
11. **Attribution held under concurrency.** Two agents interleaved via `asyncio.gather`, each with a
    subagent, and every event had the correct parent and root. (Tested with explicit handles; the
    implicit scope stack wasn't tested.)
12. **Overhead is negligible.** About 0.18 ms per tool call and 0.19 ms per LLM call with
    observability + PII on (median, n=2000, p95 about 0.25 ms). ATOF is about 1.15 KB per call even
    for tiny payloads.

## Not tested
Real Claude Code via the gateway, network OTLP export to a live backend, adaptive/ACG, the daemon, and streaming. (Local OTel/OpenInference file export was tested; see below.)

## OpenTelemetry export test (run 06-otel)

Same tiered fleet (fence v2) exported to three local OTLP JSON-lines file sinks: `full`, `gen_ai`,
`openinference`. No network. Analyzer: `scripts/analyze_otel.py`.

| Projection | Alice (L2) content spans | Alice token attrs | Ops (L4) token attrs | Owner/tier context carried? |
|---|---|---|---|---|
| full | 0 / 9 | none | `nemo_relay.end.data.usage` | yes (`nemo_relay.*.metadata.relay.*`) |
| gen_ai | 0 / 9 | none | `gen_ai.usage.input_tokens/output_tokens` | **no** |
| openinference | 0 / 9 | none | `llm.token_count.*` | yes (`openinference.metadata.relay.*`) |

13. **The source-side fence holds in every OTel projection.** 0 content spans for the personal agent.
14. **L2 tokens are lost in every OTel projection.** ATOF kept `category_profile.usage` after
    fencing, but the projections derive token attributes from the content-bearing annotations, so
    the personal agent exports zero token data. Grafana-style dashboards (Victor's L2) can't be
    built from fenced spans. This confirms finding 5 across all 5 output formats.
15. **The `gen_ai` projection drops custom owner/tier context.** It emits GenAI semconv only, so
    `relay.owner` and `relay.privacy_tier` disappear. `gen_ai` is the pipeline Relay adds
    automatically when `OTEL_EXPORTER_OTLP_ENDPOINT` is set, so a collector-side fence like Nous's
    can't route on who or what tier from standard spans.
16. **Content is duplicated inside spans.** `full` carries it as both `data.*` and `input/output.*`;
    `openinference` carries `input.value`, `llm.*_messages` and `nemo_relay.*` copies. That means
    more storage and more surface to redact.

## ⚠️ Correction: native sanitizer path (run 07-native-v3)

Fence v3 used Relay's native scope-local **LLM and tool sanitizers** (`register_llm_sanitize_request`,
`register_llm_sanitize_response`, `register_tool_sanitize_request/response`) plus a mark sanitizer,
instead of generic scope event sanitizers.

| Output | Alice (L2) content | Alice tokens |
|---|---|---|
| ATOF | 0 | kept |
| ATIF | 0 | `final_metrics` 120 prompt / 30 completion, 3 steps (same as shared agent) |
| OTel full | 0 spans | `nemo_relay.end.data.usage` |
| OTel gen_ai | 0 spans | `gen_ai.usage.input_tokens/output_tokens` |
| OTel openinference | 0 spans | `llm.token_count.*` |

**This supersedes findings 5, 6 and 14.** Relay *can* produce content-free + metrics-preserving
telemetry. Those losses were artifacts of using event sanitizers (fences v1/v2).

**What still holds (reframed as developer experience):**
- The correct path is not the obvious one: 2 of 3 attempts leaked content (v1) or lost metrics (v2).
  Nothing in config or validation warned about either failure.
- Getting it right took 5 separate callbacks across 3 registries, plus knowledge of the provider's
  response shape (the v3 response sanitizer is OpenAI-chat-specific; a multi-provider partner needs
  one per codec).
- There's still no declarative tier, and the `gen_ai` projection still drops owner/tier context (15).

## Experiment 8: content-free harness A/B eval (run 08-harness-eval)

Synthetic re-creation of Patrick's livestream case: a baseline harness that web-searches (and often
compacts) vs. a skill-first harness. 15 runs per arm, every run a personal agent fenced with native
sanitizers (v3). A canary secret was placed in every prompt, response and tool result.

| Arm | Pass | LLM calls | Tool calls | Tokens | Runs with compaction | ms |
|---|---|---|---|---|---|---|
| baseline | 14/15 | 4.5 | 2.8 | 10,509 | 73% | 33 |
| skill | 13/15 | 2.0 | 1.0 | 2,350 | 0% | 13 |

17. **Harness A/B evaluation works on content-free data.** 0 canary hits in ATOF and in all 30 ATIF
    files, yet arm, call counts, tool names, tokens, compaction and duration were all measurable. The
    pass rates are within noise (n=15) while tokens differ about 4.5×, mirroring the ToolPerf lesson.
    The values are synthetic by construction; what this demonstrates is the measurement.
18. **Privacy fences silently delete eval outcomes.** The pass/fail label emitted in mark `data` was
    removed by the fence; only the copy in `metadata` survived. There's no documented channel for
    labels and scores that should pass a privacy fence.
19. **Arm attribution needs context at birth.** It worked only because `eval.arm` was passed as scope
    `metadata=` at creation (the same issue as finding 8 / "context at birth").

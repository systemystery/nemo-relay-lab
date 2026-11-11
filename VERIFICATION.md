# Verification — 2026-11-11

Every finding in [FINDINGS.md](FINDINGS.md) was re-checked two ways:

1. **Original logs** from the lab run on 2026-11-10 (in `runs/`).
2. **A clean re-run** on a second machine: fresh venv, Python 3.12, `nemo-relay==0.11.1` from PyPI
   (still the latest release on 2026-11-11), every experiment re-run with `scripts/run_all.sh`.

Checks are scripted, not eyeballed: `scripts/verify_findings.py` (findings 2-11),
`scripts/analyze_otel.py` (13-16 and the v3 correction), `scripts/analyze_eval.py` (17-19).

| # | Finding | Original logs | Clean re-run | How it was checked |
|---|---|---|---|---|
| 1 | Quickstart on `main` doesn't install | — | **Holds** | `main` docs (`docs/getting-started/quick-start/python.mdx`) still say `uv add nemo-relay==1.0.0`; PyPI's newest is 0.11.1 (2026-11-04) |
| 2 | "Full payloads off" still captures content | Holds | Holds | Prompt, model reply and tool args all present in ATOF with `enable_full_payloads = false` |
| 3 | `x-dynamo-session-id` injected by default | Holds | Holds | Header present in recorded LLM requests |
| 4 | Per-agent privacy tiers possible, hand-built | Holds | Holds | Personal subtree: 0 of 21 events carry content; shared agent: 8 do; tier context on all 19 descendants |
| 5 | Fence v1 leaked prompts into ATIF | Holds | Not re-run | v1 code was replaced by v2 in `fleet_lab.py`; original `runs/03-tiered` trajectories contain the prompt in `extra.observed_events` |
| 6 | Content-free agent nearly invisible in ATIF (v2) | Holds | Holds | Personal trajectory 3 steps → 1, `final_metrics` loses token totals |
| 7 | No response codec → tokens only in raw content | Holds | Holds | `researcher-llm` has no `annotated_response`; usage only inside `data` |
| 8 | Root agent's start event can't carry injected context | Holds | Holds | Root start metadata is only the `metadata=` passed at creation |
| 9 | Blocked call auditable as "blocked", not "what was attempted" | Holds | Holds | 2 block marks with reason; `rm -rf` appears 0 times in the log; guardrail recorded as its own scope |
| 10 | Regex PII redaction is narrow | Holds | Holds | Email + card redacted; phone and "bob smith" pass; `card [REDACTED]and` spacing slip |
| 11 | Attribution holds under concurrency | Holds | Holds | 42 events, 0 whose parent chain disagrees with its propagation root |
| 12 | Overhead negligible | 0.18 / 0.19 ms | 0.11-0.12 / 0.12-0.17 ms | Median added per tool / LLM call, n = 2,000. Different hardware; same conclusion |
| 13 | Source-side fence holds in every OTel projection | Holds | Holds | Personal agent: 0 of 9 spans with content in `full`, `gen_ai`, `openinference` |
| 14 | Fence v2 loses tokens in every OTel projection | Holds | Holds | No token attributes on personal spans; superseded by the v3 correction |
| 15 | `gen_ai` projection drops owner/tier context | Holds | Holds | `relay.owner` / `relay.privacy_tier` present in `full` and `openinference`, absent in `gen_ai` |
| 16 | Content duplicated inside spans | Holds | Holds | `full`: `data.*` and `input/output.*`; `openinference`: `input.value`, `llm.*_messages`, `nemo_relay.*` |
| v3 | Native sanitizers: 0 content + full metrics | Holds | Holds | Personal ATIF: 3 steps, 120 prompt / 30 completion tokens, no content; token attrs in all 3 OTel projections |
| 17 | Harness A/B works on content-free data | Holds | Holds | 0 canary hits in ATOF and 30/30 ATIF files; calls, tools, tokens, compaction measurable |
| 18 | Privacy fence silently deletes eval outcomes | Holds | Holds | `pass(data)` lost in both arms; only the `metadata` copy survives |
| 19 | Arm attribution needs context at birth | Holds | Holds | Arm recovered only from `metadata=` at scope creation |

## Caveats, stated plainly

- **Experiment 8's numbers are synthetic by design.** Token counts are fixed in the mock model and pass/fail
  is a seeded random draw, so the re-run reproduces them exactly. The finding is that the *measurement*
  works on content-free data, not that skill-first harnesses use 78% fewer tokens.
- **Finding 5 is from the original logs only.** The v1 fence code is no longer in `fleet_lab.py`.
- **Not tested** (unchanged from FINDINGS.md): a real harness through the gateway, network OTLP export to a
  live backend, adaptive/ACG, the daemon, streaming.
- **Not yet compared with `main`** (1.0.0, unreleased). Planned as a follow-up.

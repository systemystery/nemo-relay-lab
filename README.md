# NeMo Relay sandbox lab

A hands-on test of [NVIDIA NeMo Relay](https://github.com/NVIDIA/NeMo-Relay) 0.11.1 from an enterprise
operator's point of view: **can one agent fleet keep full records for shared agents and stay content-free
for personal ones, without losing the metrics needed to evaluate and tune them?**

Fully offline: mock model and tool callbacks, no API keys, no real user data.

## TL;DR

- **Relay can do it.** With its native scope-local LLM and tool sanitizers, a personal agent exported
  **zero content** but kept token metrics in all five outputs (ATOF, ATIF, and three OpenTelemetry projections).
- **The correct path is hard to find.** Two of three attempts failed silently: one leaked prompts into ATIF,
  one wiped token metrics. Nothing warned either time. `enable_full_payloads = false` still records prompts,
  responses, and tool arguments.
- **Context gets lost.** The `gen_ai` OpenTelemetry projection drops owner and privacy-tier labels, and an
  agent's own start event can't carry injected context.
- **Privacy and evals collide.** A harness A/B eval ran on content-free telemetry with 0 leaked canary strings,
  but the privacy fence silently deleted the pass/fail label.
- **Cheap to run.** ~0.1-0.2 ms added per model or tool call (median, n = 2,000).

19 findings in [FINDINGS.md](FINDINGS.md). All re-checked on a clean machine on 2026-11-11:
[VERIFICATION.md](VERIFICATION.md). Product write-up: [brief.html](brief.html).

## Experiments

| Run | Question |
|---|---|
| `01-quickstart` | Does the official first run work? |
| `02-baseline` | What is recorded when nobody configures privacy? |
| `03-tiered` | Fence v1 (generic event sanitizers): can one agent be treated differently? |
| `04-tiered-v2` | Fence v2 (stricter): what does it take to remove all content? |
| `05-overhead` | Does Relay slow agents down? |
| `06-otel` | Does the fence survive into `full`, `gen_ai` and `openinference` spans? |
| `07-native-v3` | Fence v3 (native LLM/tool sanitizers): content-free *and* metrics? |
| `08-harness-eval` | Can a harness change be A/B-evaluated without reading content? |

Each `runs/<run>/` holds the `plugins.toml` used and the raw logs (`logs/events.jsonl` ATOF,
`logs/atif/` trajectories, `logs/otel-*/` OTLP JSON lines).

## Reproduce

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
PY=.venv/bin/python bash scripts/run_all.sh
```

Writes fresh logs to `rerun/` and prints every check.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/fleet_lab.py` | The fake fleet: a personal agent, a shared ops agent, subagents, PII, an `rm -rf`. Modes `baseline`, `tiered`, `tiered-v3` |
| `scripts/harness_eval.py` | Experiment 8: harness A/B on content-free data |
| `scripts/overhead.py` | 2,000-call overhead benchmark |
| `scripts/analyze_otel.py` | Content leaks, tokens and owner context in the three OTel formats |
| `scripts/analyze_eval.py` | Scores the harness A/B from the event log |
| `scripts/verify_findings.py` | Scripted checks for findings 2-11 |
| `scripts/run_all.sh` | Re-runs everything and all checks |

## Not tested

A real harness through the gateway, network OTLP export to a live backend, adaptive/ACG, the daemon,
streaming. Experiment 8's values are synthetic by construction; it demonstrates the measurement, not a
harness result.

---

Independent work by Nimish Singhal. Not affiliated with or endorsed by NVIDIA. Built with Claude Code as
an engineering partner; the product questions and interpretation are mine. `quickstart.py` and the
quickstart `plugins.toml` are from the NeMo Relay repository (Apache-2.0).

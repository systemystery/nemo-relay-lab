#!/usr/bin/env bash
# Re-run every experiment into ./rerun/<run>/ and check the findings against the fresh logs.
# Needs Python >= 3.11 and: pip install nemo-relay==0.11.1
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; PY="${PY:-python3}"; OUT="${OUT:-$ROOT/rerun}"
rm -rf "$OUT"; mkdir -p "$OUT"
run() { local name=$1; shift; mkdir -p "$OUT/$name"; cp "$ROOT/runs/$name/plugins.toml" "$OUT/$name/"
        (cd "$OUT/$name" && "$PY" -I "$@" > out.txt 2>&1); echo "ran $name"; }
run 01-quickstart   "$ROOT/scripts/quickstart.py"
run 02-baseline     "$ROOT/scripts/fleet_lab.py" baseline
run 04-tiered-v2    "$ROOT/scripts/fleet_lab.py" tiered
run 06-otel         "$ROOT/scripts/fleet_lab.py" tiered
run 07-native-v3    "$ROOT/scripts/fleet_lab.py" tiered-v3
run 08-harness-eval "$ROOT/scripts/harness_eval.py"
mkdir -p "$OUT/05-overhead"; cp "$ROOT/runs/05-overhead/plugins.toml" "$OUT/05-overhead/"
(cd "$OUT/05-overhead" && "$PY" -I "$ROOT/scripts/overhead.py" plugins.toml | tee out.txt)
echo; "$PY" -I "$ROOT/scripts/verify_findings.py" "$OUT/02-baseline" "$OUT/04-tiered-v2"
for r in 06-otel 07-native-v3; do echo; echo "## $r"; "$PY" -I "$ROOT/scripts/analyze_otel.py" "$OUT/$r/logs"; done
echo; "$PY" -I "$ROOT/scripts/analyze_eval.py" "$OUT/08-harness-eval/logs/events.jsonl"

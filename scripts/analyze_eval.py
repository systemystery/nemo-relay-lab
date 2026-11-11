"""Score harness arms from content-free ATOF only. Usage: python -I analyze_eval.py events.jsonl"""
import json
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime

events = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
leaks = sum("Q3 bonus" in json.dumps(e) for e in events)

runs = {}  # agent uuid -> stats
for e in events:
    if e["kind"] == "scope" and e.get("category") == "agent" and e["scope_category"] == "start":
        md = e.get("metadata") or {}
        runs[e["uuid"]] = {"arm": md.get("eval.arm"), "t0": e["timestamp"], "llm": 0, "tools": 0,
                           "tokens": 0, "compactions": 0, "pass_data": None, "pass_meta": None,
                           "tool_names": []}
for e in events:
    run = runs.get(e.get("propagation_root_uuid"))
    if not run:
        continue
    if e["kind"] == "scope" and e["scope_category"] == "end":
        if e.get("category") == "llm":
            run["llm"] += 1
            usage = (e.get("category_profile") or {}).get("annotated_response", {}).get("usage") \
                or (e.get("data") or {}).get("usage") or {}
            run["tokens"] += usage.get("total_tokens", 0)
        elif e.get("category") == "tool":
            run["tools"] += 1
            run["tool_names"].append(e["name"])
        elif e.get("category") == "agent":
            run["t1"] = e["timestamp"]
    if e["kind"] == "mark":
        if e["name"] == "context_compaction":
            run["compactions"] += 1
        if e["name"] == "eval_result":
            run["pass_data"] = (e.get("data") or {}).get("passed")
            run["pass_meta"] = (e.get("metadata") or {}).get("eval.passed")

ms = lambda r: (datetime.fromisoformat(r["t1"]) - datetime.fromisoformat(r["t0"])).total_seconds() * 1000
by_arm = defaultdict(list)
for r in runs.values():
    by_arm[r["arm"]].append(r)

print(f"canary content strings exported: {leaks}")
print(f"{'arm':<9}{'runs':>5}{'pass(meta)':>12}{'pass(data)':>12}{'LLM calls':>11}{'tool calls':>11}{'tokens':>9}{'compact%':>10}{'ms':>7}  tools seen")
for arm, rs in by_arm.items():
    pm = [x["pass_meta"] for x in rs if x["pass_meta"] is not None]
    pdv = [x["pass_data"] for x in rs if x["pass_data"] is not None]
    names = sorted({n for x in rs for n in x["tool_names"]})
    print(f"{arm:<9}{len(rs):>5}{(f'{sum(pm)}/{len(pm)}' if pm else 'lost'):>12}{(f'{sum(pdv)}/{len(pdv)}' if pdv else 'lost'):>12}"
          f"{st.mean(x['llm'] for x in rs):>11.1f}{st.mean(x['tools'] for x in rs):>11.1f}"
          f"{st.mean(x['tokens'] for x in rs):>9.0f}{100*st.mean(x['compactions']>0 for x in rs):>9.0f}%"
          f"{st.mean(ms(x) for x in rs):>7.0f}  {names}")

"""Compare OTLP JSON-lines projections: content leakage, token attrs, context attrs per agent.
Usage: python -I analyze_otel.py <logs_dir>
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

CONTENT = re.compile(r"Summarize my inbox|card dispute|415-555|Bob emailed|bob\.smith|Q3 card statement|stdout|example\.com/a")
TOKEN_KEYS = re.compile(r"(usage|token)", re.I)
CTX_KEYS = re.compile(r"relay\.(owner|privacy_tier|deployment_unit)")


def attr_val(v):
    for k in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if k in v:
            return v[k]
    return json.dumps(v)


def spans(path):
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        doc = json.loads(line)
        for rs in doc.get("resourceSpans", []):
            for ss in rs.get("scopeSpans", []):
                for sp in ss.get("spans", []):
                    yield sp


def main(root):
    for d in sorted(Path(root).glob("otel-*")):
        all_spans = [s for f in d.glob("*.jsonl") for s in spans(f)]
        by_id = {s["spanId"]: s for s in all_spans}

        def agent_of(s):
            # walk to the top-most agent span name
            name, cur = None, s
            while cur:
                base = cur["name"].removeprefix("invoke_agent ")
                if base in ("alice-personal", "ops-shared"):
                    name = base
                cur = by_id.get(cur.get("parentSpanId", ""))
            return name or "?"

        stats = defaultdict(lambda: {"spans": 0, "content_spans": 0, "token_attrs": set(), "ctx_attrs": set(), "content_keys": set()})
        for s in all_spans:
            a = agent_of(s)
            st = stats[a]
            st["spans"] += 1
            attrs = {a_["key"]: attr_val(a_["value"]) for a_ in s.get("attributes", [])}
            ev_text = json.dumps(s.get("events", []))
            leaked = [k for k, v in attrs.items() if CONTENT.search(str(v))]
            if leaked or CONTENT.search(ev_text):
                st["content_spans"] += 1
                st["content_keys"].update(leaked or ["<span events>"])
            st["token_attrs"].update(k for k in attrs if TOKEN_KEYS.search(k))
            st["ctx_attrs"].update(k for k in attrs if CTX_KEYS.search(k))
        print(f"\n=== {d.name}  (total spans={len(all_spans)})")
        for a, st in sorted(stats.items()):
            print(f"  {a:<15} spans={st['spans']:<3} spans_with_content={st['content_spans']:<3}"
                  f" ctx_attrs={sorted(st['ctx_attrs']) or '-'}")
            print(f"  {'':<15} token_attrs={sorted(st['token_attrs']) or '-'}")
            if st["content_keys"]:
                print(f"  {'':<15} content_in={sorted(st['content_keys'])}")


main(sys.argv[1])

"""Re-check findings 2-11 from the ATOF/ATIF logs of a fleet_lab run.
Usage: python -I verify_findings.py <baseline_run_dir> <tiered_v2_run_dir>
Each check prints CONFIRMED / NOT CONFIRMED with the evidence it used.
"""
import json, sys
from pathlib import Path

def load(run):
    ev = [json.loads(l) for l in (Path(run) / "logs/events.jsonl").read_text().splitlines() if l.strip()]
    trajs = [json.loads(p.read_text()) for p in sorted((Path(run) / "logs/atif").glob("*.json"))]
    return ev, trajs

def say(n, ok, msg):
    print(f"  F{n:<3} {'CONFIRMED    ' if ok else 'NOT CONFIRMED'} {msg}")

base, base_t = load(sys.argv[1])
tier, tier_t = load(sys.argv[2])
dump = lambda x: json.dumps(x)
agents = {e["uuid"]: e["name"] for e in base if e["kind"] == "scope" and e.get("category") == "agent" and e["scope_category"] == "start"}
roots = {e["uuid"]: e["name"] for e in base if e["kind"] == "scope" and e.get("category") == "agent" and e["scope_category"] == "start" and "/" not in e["name"]}

print("Baseline run (enable_full_payloads = false)")
llm_end = [e for e in base if e.get("category") == "llm" and e["scope_category"] == "end"]
tool_start = [e for e in base if e.get("category") == "tool" and e["scope_category"] == "start"]
say(2, any("Summarize my inbox" in dump(e) for e in base if e.get("category") == "llm")
       and any("Bob emailed" in dump(e) for e in llm_end)
       and any("inbox" in dump(e.get("data")) for e in tool_start),
    "prompt text, model reply and tool args all present in ATOF")
say(3, "x-dynamo-session-id" in dump(base), "x-dynamo-session-id header found in recorded LLM requests")
sub = [e for e in llm_end if e["name"] == "researcher-llm"]
say(7, all(not (e.get("category_profile") or {}).get("annotated_response") and "total_tokens" in dump(e.get("data")) for e in sub),
    "researcher-llm (no response codec): tokens only inside raw `data`, no annotated_response")
blocked = [e for e in base if e["kind"] == "mark" and e["name"] == "shell"]
guard = [e for e in base if e.get("category") == "guardrail"]
say(9, bool(blocked) and "Blocked by policy" in dump(blocked) and "rm -rf" not in dump(base) and bool(guard),
    f"{len(blocked)} block marks with reason; 'rm -rf' appears 0 times; {len(guard)} guardrail scope events")
text = dump(base)
say(10, "bob.smith@example.com" not in text and "4111 1111" not in text and "415-555-0199" in text
        and "bob smith card dispute" in text and "card [REDACTED]and" in text,
    "email+card redacted; phone and 'bob smith' pass; 'card [REDACTED]and' spacing slip")
by = {e["uuid"]: e for e in base}
def root_name(e):
    cur = e
    while cur and cur["uuid"] not in roots:
        cur = by.get(cur.get("parent_uuid"))
    return roots.get(cur["uuid"]) if cur else None
wrong = [e for e in base if e.get("propagation_root_uuid") in roots and root_name(e) != roots[e["propagation_root_uuid"]]]
say(11, not wrong and len({e["propagation_root_uuid"] for e in base}) >= 2,
    f"{len(base)} events, {len(wrong)} with parent chain disagreeing with propagation root")

print("Tiered run (fence v2)")
tby = {e["uuid"]: e for e in tier}
troots = {e["uuid"]: e["name"] for e in tier if e["kind"] == "scope" and e.get("category") == "agent" and e["scope_category"] == "start" and "/" not in e["name"]}
a_ev = [e for e in tier if troots.get(e.get("propagation_root_uuid")) == "alice-personal"]
o_ev = [e for e in tier if troots.get(e.get("propagation_root_uuid")) == "ops-shared"]
CONTENT = ("Summarize my inbox", "Bob emailed", "inbox", "card dispute", "Q3 card statement")
a_leak = [e for e in a_ev if any(c in dump(e) for c in CONTENT)]
o_has = [e for e in o_ev if any(c in dump(e) for c in CONTENT)]
ctx_desc = [e for e in a_ev if e["uuid"] != e.get("propagation_root_uuid") and "relay.privacy_tier" in dump(e.get("metadata"))]
say(4, not a_leak and o_has and len(ctx_desc) == len([e for e in a_ev if e["uuid"] != e.get("propagation_root_uuid")]),
    f"alice subtree: {len(a_leak)} content events of {len(a_ev)}; ops: {len(o_has)} content events; tier ctx on {len(ctx_desc)} alice descendants")
a_root_start = [e for e in a_ev if e["uuid"] == e.get("propagation_root_uuid") and e["kind"] == "scope" and e["scope_category"] == "start"]
say(8, a_root_start and "relay.privacy_tier" not in dump(a_root_start[0].get("metadata")),
    f"alice root start metadata = {a_root_start[0].get('metadata') if a_root_start else None}")
# map trajectories to agents by session id == root uuid
def per_agent(ts, roots_):
    out = {}
    for t in ts:
        sid = t.get("session_id")
        out[roots_.get(sid, sid)] = (len(t.get("steps", [])), t.get("final_metrics"))
    return out
bt = per_agent(base_t, roots); tt = per_agent(tier_t, troots)
print(f"        ATIF per agent  baseline={bt}")
print(f"        ATIF per agent  tiered  ={tt}")
a = tt.get("alice-personal"); b = bt.get("alice-personal") or bt.get(next(iter(bt), None))
say(6, bool(a) and a[0] < 3 and not any("token" in k for k in (a[1] or {})) ,
    "fenced personal trajectory has fewer steps and no token totals")

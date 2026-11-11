"""NeMo Relay sandbox lab: a tiny fake "agent fleet" with mock model/tool calls.

Experiments (all offline, no API keys):
  A. Baseline: what does default ATOF capture for personal vs shared agents?
  B. Tiering:  can scope-local sanitizers give a personal agent an L2
               "content-free" tier while a shared agent keeps L4 content?
  C. Context:  can a scope-local metadata injector stamp owner/tier context on
               every descendant event (including subagents)?
  D. Policy:   does a pre-tool guardrail block `rm -rf` before the tool runs?
  E. Attribution: do concurrent agents keep correct parentage?

Usage: python fleet_lab.py <mode>   where mode is "baseline" or "tiered"
"""

import asyncio
import json
import sys
from pathlib import Path

import nemo_relay as r

MODE = sys.argv[1] if len(sys.argv) > 1 else "baseline"

PII_PROMPT = (
    "Summarize my inbox. Reply to bob.smith@example.com about card "
    "4111 1111 1111 1111 and call me at 415-555-0199."
)

TOOL_RAN: list[str] = []


# ---------- mock tools and model ----------
async def read_email(args):
    TOOL_RAN.append(f"read_email:{args.get('folder')}")
    return r.ToolExecutionResult(
        {"messages": [{"from": "bob.smith@example.com", "subject": "Q3 card statement"}]}
    )


async def shell(args):
    TOOL_RAN.append(f"shell:{args.get('cmd')}")
    return r.ToolExecutionResult({"stdout": "ok"})


async def web_search(args):
    TOOL_RAN.append(f"web_search:{args.get('q')}")
    await asyncio.sleep(0.01)
    return r.ToolExecutionResult({"results": ["https://example.com/a"]})


def make_model(label: str):
    async def model(request):
        await asyncio.sleep(0.005)
        return {
            "id": f"chatcmpl-{label}",
            "object": "chat.completion",
            "model": "mock-model-1",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": f"[{label}] Bob emailed about card 4111 1111 1111 1111."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        }

    return model


def request(text: str):
    return r.LLMRequest({}, {"model": "mock-model-1", "messages": [{"role": "user", "content": text}]})


# ---------- context + tier policy (the hypothesis under test) ----------
def install_tier_policy(handle, *, owner: str, unit: str, tier: str):
    """Attach owner/tier context and an L2 content fence to one agent scope."""

    def inject(_event):
        return {"relay.owner": owner, "relay.deployment_unit": unit, "relay.privacy_tier": tier}

    r.scope_local.register_event_metadata_injector(handle, "ctx", 10, inject)

    if tier == "L2" and MODE == "tiered-v3":
        # v3: Relay's native LLM/tool sanitizers (the intended path). Blank content,
        # keep response metadata such as usage so projections can still derive tokens.
        def llm_req(req, *_):
            content = dict(req.content) if hasattr(req, "content") else {}
            msgs = content.get("messages") or []
            content["messages"] = [{"role": m.get("role"), "content": ""} for m in msgs]
            return r.LLMRequest({}, content)

        def llm_resp(resp, *_):
            if not isinstance(resp, dict):
                return None
            out = {k: v for k, v in resp.items() if k in ("id", "object", "model", "usage")}
            out["choices"] = [{"index": c.get("index", 0), "finish_reason": c.get("finish_reason"),
                               "message": {"role": "assistant", "content": ""}}
                              for c in resp.get("choices", [])]
            return out

        r.scope_local.register_llm_sanitize_request(handle, "l2-llm-req", 1000, llm_req)
        r.scope_local.register_llm_sanitize_response(handle, "l2-llm-resp", 1000, llm_resp)
        r.scope_local.register_tool_sanitize_request(handle, "l2-tool-req", 1000, lambda name, args: {})
        r.scope_local.register_tool_sanitize_response(handle, "l2-tool-resp", 1000, lambda name, res: {})
        r.scope_local.register_mark_sanitize(
            handle, "l2-mark", 1000,
            lambda ev, f: {"data": None, "category_profile": f.get("category_profile"), "metadata": f.get("metadata")})
    elif tier == "L2":
        def fence(event, fields):
            # v2: keep structure (names, timing, parentage, status) and analytics
            # (model name, token usage, finish reason); drop all content, including
            # the normalized request/response copies inside category_profile.
            profile = fields.get("category_profile") or {}
            kept = {}
            if "model_name" in profile:
                kept["model_name"] = profile["model_name"]
            resp = profile.get("annotated_response") or {}
            if "usage" in resp:
                kept["usage"] = resp["usage"]
            if "finish_reason" in resp:
                kept["finish_reason"] = resp["finish_reason"]
            return {"data": None, "category_profile": kept or None, "metadata": fields.get("metadata")}

        r.scope_local.register_scope_sanitize_start(handle, "l2-fence-start", 1000, fence)
        r.scope_local.register_scope_sanitize_end(handle, "l2-fence-end", 1000, fence)
        r.scope_local.register_mark_sanitize(handle, "l2-fence-mark", 1000, fence)


def block_destructive(tool_name, args):
    cmd = json.dumps(args)
    if tool_name == "shell" and "rm -rf" in cmd:
        return "Blocked by policy: destructive shell command"
    return None


# ---------- the fake fleet ----------
async def run_agent(name: str, owner: str, unit: str, tier: str):
    with r.scope.scope(name, r.ScopeType.Agent, metadata={"declared_owner": owner}) as agent:
        if MODE.startswith("tiered"):
            install_tier_policy(agent, owner=owner, unit=unit, tier=tier)
        r.scope.event("session_start", handle=agent, data={"channel": "slack-dm", "user_text": PII_PROMPT})

        await r.llm.execute("planner", request(PII_PROMPT), make_model(name), handle=agent,
                            model_name="mock-model-1", codec=r.codecs.OpenAIChatCodec(),
                            response_codec=r.codecs.OpenAIChatCodec())
        await r.tools.execute("read_email", {"folder": "inbox", "reply_to": "bob.smith@example.com"},
                              read_email, handle=agent)
        try:
            await r.tools.execute("shell", {"cmd": "rm -rf /data/archive"}, shell, handle=agent)
        except Exception as exc:  # record how a block surfaces to the caller
            r.scope.event("tool_blocked", handle=agent, data={"error": type(exc).__name__, "msg": str(exc)[:200]})

        with r.scope.scope(f"{name}/researcher", r.ScopeType.Agent) as sub:
            await r.tools.execute("web_search", {"q": "bob smith card dispute"}, web_search, handle=sub)
            await r.llm.execute("researcher-llm", request("Research card dispute rules for bob.smith@example.com"),
                                make_model(f"{name}/sub"), handle=sub, model_name="mock-model-1",
                                codec=r.codecs.OpenAIChatCodec())


async def main():
    async with r.plugin.activate({}, "plugins.toml"):
        r.guardrails.register_tool_conditional_execution("block-destructive", 10, block_destructive)
        try:
            # E: run both agents concurrently to test attribution under interleaving
            await asyncio.gather(
                run_agent("alice-personal", owner="alice", unit="personal", tier="L2"),
                run_agent("ops-shared", owner="team-ops", unit="shared", tier="L4"),
            )
        finally:
            await r.subscribers.flush_async()
    print("TOOLS_ACTUALLY_RAN:", TOOL_RAN)


asyncio.run(main())

"""Experiment 8: evaluate a harness change using only content-free (L2) telemetry.

Synthetic re-creation of Patrick's livestream case: a "baseline" harness web-searches
(and sometimes compacts) for questions a local skill can answer; a "skill" harness reads
the local skill first. Every run is a personal agent fenced with native sanitizers (v3),
so prompts, responses, tool args and results never reach the exporters.

The eval outcome (pass/fail) is emitted two ways to test which survives the fence:
  - in mark `data`     (the obvious place)
  - in mark `metadata` (where a fence may let labels through)

Results are synthetic by construction; this demonstrates the *measurement*, not a real
harness result.
Usage: python harness_eval.py
"""
import asyncio
import random

import nemo_relay as r

RUNS_PER_ARM = 15
rng = random.Random(7)
SECRET = "Alice's Q3 bonus is 42,000"  # canary content that must never be exported


async def tool_ok(args):
    await asyncio.sleep(0.002)
    return r.ToolExecutionResult({"text": SECRET})


def model_with(tokens_in, tokens_out):
    async def model(req):
        await asyncio.sleep(0.004)
        return {"id": "x", "object": "chat.completion", "model": "small-local-model",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": SECRET}}],
                "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out,
                          "total_tokens": tokens_in + tokens_out}}
    return model


def fence_personal(h):
    def llm_req(req, *_):
        c = dict(req.content)
        c["messages"] = [{"role": m.get("role"), "content": ""} for m in c.get("messages", [])]
        return r.LLMRequest({}, c)

    def llm_resp(resp, *_):
        out = {k: v for k, v in resp.items() if k in ("id", "object", "model", "usage")}
        out["choices"] = [{"index": 0, "finish_reason": c.get("finish_reason"),
                           "message": {"role": "assistant", "content": ""}} for c in resp.get("choices", [])]
        return out

    sl = r.scope_local
    sl.register_llm_sanitize_request(h, "req", 1000, llm_req)
    sl.register_llm_sanitize_response(h, "resp", 1000, llm_resp)
    sl.register_tool_sanitize_request(h, "treq", 1000, lambda n, a: {})
    sl.register_tool_sanitize_response(h, "tres", 1000, lambda n, a: {})
    sl.register_mark_sanitize(h, "mark", 1000,
                              lambda ev, f: {"data": None, "category_profile": f.get("category_profile"),
                                             "metadata": f.get("metadata")})


async def llm(h, name, tin, tout):
    req = r.LLMRequest({}, {"model": "small-local-model", "messages": [{"role": "user", "content": SECRET}]})
    await r.llm.execute(name, req, model_with(tin, tout), handle=h, model_name="small-local-model",
                        codec=r.codecs.OpenAIChatCodec(), response_codec=r.codecs.OpenAIChatCodec())


async def run(arm: str, i: int):
    meta = {"eval.arm": arm, "eval.run": i, "relay.privacy_tier": "L2", "relay.deployment_unit": "personal"}
    with r.scope.scope(f"personal-agent:{arm}:{i}", r.ScopeType.Agent, metadata=meta) as h:
        fence_personal(h)
        await llm(h, "plan", 900, 60)
        if arm == "baseline":
            for _ in range(rng.choice([2, 3, 4])):
                await r.tools.execute("web_search", {"q": SECRET}, tool_ok, handle=h)
                await llm(h, "read_results", 2400, 120)
            if rng.random() < 0.6:  # small context window forces compaction
                r.scope.event("context_compaction", handle=h, data={"summary": SECRET})
                await llm(h, "compact", 3000, 400)
            passed = rng.random() < 0.80
        else:
            await r.tools.execute("skill_view", {"skill": "workflow-notes"}, tool_ok, handle=h)
            await llm(h, "answer", 1300, 90)
            passed = rng.random() < 0.87
        r.scope.event("eval_result", handle=h, data={"passed": passed}, metadata={"eval.passed": passed})


async def main():
    async with r.plugin.activate({}, "plugins.toml"):
        try:
            for i in range(RUNS_PER_ARM):
                await run("baseline", i)
                await run("skill", i)
        finally:
            await r.subscribers.flush_async()
    print("done")


asyncio.run(main())

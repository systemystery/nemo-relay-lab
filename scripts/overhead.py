"""Rough per-call overhead of Relay-managed tool and LLM calls vs. direct calls.
Mock callbacks do no work, so this measures Relay's own cost per call.
Usage: python overhead.py <plugins.toml>
"""
import asyncio
import statistics
import sys
import time

import nemo_relay as r

N = 2000


async def tool(args):
    return r.ToolExecutionResult({"ok": True})


async def model(req):
    return {"id": "x", "object": "chat.completion", "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}


def req():
    return r.LLMRequest({}, {"model": "m", "messages": [{"role": "user", "content": "hello alice@example.com"}]})


async def bench(label, fn):
    samples = []
    for _ in range(N):
        t = time.perf_counter()
        await fn()
        samples.append((time.perf_counter() - t) * 1e6)
    samples.sort()
    print(f"{label:<34} median={statistics.median(samples):8.1f}us  p95={samples[int(N*0.95)]:8.1f}us")
    return statistics.median(samples)


async def main():
    direct_t = await bench("direct tool call", lambda: tool({"q": 1}))
    direct_m = await bench("direct model call", lambda: model(req()))
    async with r.plugin.activate({}, sys.argv[1]):
        with r.scope.scope("bench-agent", r.ScopeType.Agent) as h:
            relay_t = await bench("relay tool call (+obs+pii)", lambda: r.tools.execute("t", {"q": 1}, tool, handle=h))
            relay_m = await bench("relay llm call (+obs+pii)", lambda: r.llm.execute(
                "m", req(), model, handle=h, model_name="m",
                codec=r.codecs.OpenAIChatCodec(), response_codec=r.codecs.OpenAIChatCodec()))
        await r.subscribers.flush_async()
    print(f"\nadded per tool call ~{(relay_t-direct_t)/1000:.3f} ms, per llm call ~{(relay_m-direct_m)/1000:.3f} ms")


asyncio.run(main())

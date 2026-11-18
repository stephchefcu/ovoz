"""Claude connection check WITHOUT calling Anthropic: a fake server inside the test answers instead.
Run:  python tests/claude_test.py   (needs: pip install anthropic)"""
import json
import os
import sys

os.environ.update({"ANTHROPIC_API_KEY": "test-key-not-real", "CLAUDE_MODEL": "claude-sonnet-5-5",
                   "LLM_BASE_URL": "", "LLM_API_KEY": "", "LLM_MODEL": ""})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import anthropic  # noqa: E402
    import httpx2  # noqa: E402
except ImportError:
    print(f"SKIP claude_test: needs the anthropic package, which needs Python 3.10+ "
          f"(this is Python {sys.version_info.major}.{sys.version_info.minor}). The app uses keyword rules here.")
    sys.exit(0)

from app import ai  # noqa: E402


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        check.failed = True


check.failed = False
SEEN = {}
REPLY = {"mode": "ok"}


def fake_anthropic(request):
    SEEN["body"] = json.loads(request.content)
    SEEN["headers"] = dict(request.headers)
    if REPLY["mode"] == "down":
        return httpx2.Response(503, json={"type": "error", "error": {"type": "overloaded_error", "message": "x"}})
    text = json.dumps({"category": "medication", "severity": 4, "urgent": False, "near_miss": True,
                       "summary": "A medicine was nearly given to the wrong patient during a busy shift."})
    return httpx2.Response(200, json={
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "refusal" if REPLY["mode"] == "refusal" else "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10}})


ai._CLAUDE["client"] = anthropic.Anthropic(api_key="test-key-not-real", max_retries=0,
                                           http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(fake_anthropic)))

check("Claude is the AI provider when ANTHROPIC_API_KEY is set", ai.llm_provider() == "claude")
r = ai.analyze("Hamshira Dilnoza boshqa bemorga dori bermoqchi edi, oxirgi daqiqada sezdik", "staff")
b = SEEN["body"]
check("sends the model from CLAUDE_MODEL (Sonnet 5.5)", b["model"] == "claude-sonnet-5-5")
check("sends only the masked text (no names)", "Dilnoza" not in json.dumps(b) and "[NAME]" in json.dumps(b))
check("quick sorting uses low effort", b.get("output_config") == {"effort": "low"})
check("declined requests fall back to another model", b.get("fallbacks") == "default"
      and "server-side-fallback-2026-07-01" in SEEN["headers"].get("anthropic-beta", ""))
check("no sampling settings (rejected by current models)", "temperature" not in b and "top_p" not in b)
check("Claude's answer is used", r["category"] == "medication" and r["severity"] == 4 and r["near_miss"]
      and r["summary"].startswith("A medicine"))

ai.rca("medication", "Surgery", ["Dori kech berildi"], [], "uz")
check("root-cause help uses medium effort", SEEN["body"].get("output_config") == {"effort": "medium"})

REPLY["mode"] = "refusal"
r = ai.analyze("Dori kech berildi, 2 soat kutdik", "patient")
check("if Claude declines, the keyword rules take over", r["summary"] and ai.is_rule_summary(r["summary"]))

REPLY["mode"] = "down"
r = ai.analyze("Dori kech berildi, 2 soat kutdik", "patient")
check("if Claude is down, the keyword rules take over", r["category"] in ai.CATEGORIES and ai.is_rule_summary(r["summary"]))

sys.exit(1 if check.failed else 0)

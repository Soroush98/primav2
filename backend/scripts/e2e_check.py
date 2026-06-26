"""End-to-end smoke check — drives the REAL agent fleet against live Vertex AI
(Gemini) + BigQuery (`primav2.alibaba_cluster`).

This is an INTEGRATION check, not a unit test: it needs Application Default
Credentials and the cloud resources to exist. It prints every node's output so
each integration point is visible — intent (Gemini), the generated read-only SQL
(Gemini), rows (BigQuery), detection (NumPy), root-cause, and the final briefing.

Run:  uv run --directory backend python scripts/e2e_check.py ["your question"]
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ root → import app.*

from app.agent.runtime import get_agent

QUESTION = (
    sys.argv[1] if len(sys.argv) > 1
    else "Which machines show the most anomalous CPU and memory behaviour? Look at recent windows."
)


def _j(x) -> str:
    return json.dumps(x, indent=2, default=str)


async def main() -> None:
    print(f"Q: {QUESTION}\n")
    agent = get_agent()
    t0 = time.time()
    state = await agent.ainvoke({"question": QUESTION})
    dt = time.time() - t0

    print("--- focus (orchestrator → Gemini) ---")
    print(_j(state.get("focus")))
    print("\n--- sql (sql_analyst → Gemini) ---")
    print(state.get("sql"))
    print(f"\n--- rows (BigQuery) --- {len(state.get('rows') or [])} returned")
    rows = state.get("rows") or []
    if rows:
        print("first row:", _j(rows[0]))
    print("\n--- detection (MAD/EVT) ---")
    print(_j(state.get("detection")))
    print("\n--- root_cause ---")
    print(_j(state.get("root_cause")))
    if state.get("error"):
        print("\n--- error ---", state["error"])
    print("\n=== BRIEFING (narrator → Gemini) ===")
    print(state.get("briefing"))

    ok = bool(state.get("briefing")) and not state.get("error")
    print(f"\n[{'PASS' if ok else 'CHECK'}] end-to-end in {dt:.1f}s "
          f"(Gemini ×3 + BigQuery ×1, {len(rows)} rows)")


if __name__ == "__main__":
    asyncio.run(main())

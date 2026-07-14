"""将正式主图的节点更新逐条落盘，用于定位单案例停滞位置。"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
OUTPUT_DIR = PROJECT_ROOT / "output" / "dual_channel_e2e"


def main() -> int:
    from agent.graph import app

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"flexible_trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    question = "找出 2024 年营业收入和净利润都进入前 20 的公司，并按净利率排序。"
    with path.open("w", encoding="utf-8") as file:
        for update in app.compiled_graph.stream({"user_question": question}, stream_mode="updates"):
            file.write(json.dumps(update, ensure_ascii=False, default=str) + "\n")
            file.flush()
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

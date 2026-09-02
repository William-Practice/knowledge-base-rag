"""
evaluator_demo.py — 评测示例：用 eval_set.json 的评测题跑全链路问答
对每题做 检索+生成，输出答案与命中来源，人工核对关键词覆盖
"""

import json
import os

from loader import build_index
from generator import full_answer

EVAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_set.json")


def load_eval_set(path: str = EVAL_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["questions"]


def main():
    kb = build_index()
    questions = load_eval_set()
    print(f"评测集: {len(questions)} 道题\n{'=' * 56}")

    results = []
    for item in questions:
        q = item["question"]
        print(f"\n❓ Q{item['id']}: {q}")
        result = full_answer(q, kb)

        ans = result["answer"]
        kws = item.get("answer_keywords", [])
        hit = [kw for kw in kws if kw.lower() in ans.lower()]
        miss = [kw for kw in kws if kw.lower() not in ans.lower()]

        print(f"   重写: {result['rewritten']}")
        print(f"   答案: {ans[:220]}{'...' if len(ans) > 220 else ''}")
        print(f"   来源: {[s['file'] for s in result['sources']]}")
        print(f"   关键词命中: {len(hit)}/{len(kws)} {hit}")
        if miss:
            print(f"   未命中: {miss}")

        results.append({"id": item["id"], "hit": len(hit), "total": len(kws)})

    print(f"\n{'=' * 56}")
    total_hit = sum(r["hit"] for r in results)
    total_all = sum(r["total"] for r in results)
    print(f"总关键词命中率: {total_hit}/{total_all} ({total_hit / total_all:.0%})")


if __name__ == "__main__":
    main()

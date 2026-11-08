"""
eval/resolve_gold.py — 把 (section, anchors, source) 解析成 gold chunk（离线，不调 API）

为什么这样标
    "哪一段算回答了这题"如果靠人眼在几百块里挑，既慢又不可复核。
    P0 已经给每块存了 section 元信息，于是 gold 判定可以变成机械的：
       section 命中 ∧ 全部 anchors 命中 ∧ （可选）source 命中
    人能复核的是"这个章节 + 这几个锚点是否就是答案所在"，而不是"在 457 块里找哪一块"。

用法
    python eval/resolve_gold.py              # 只报告
    python eval/resolve_gold.py --write      # 把 gold 写回 eval_set_v2.json
    python eval/resolve_gold.py --show 3     # 打印前 3 题的 gold 片段
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_KB = os.path.dirname(_HERE)
sys.path.insert(0, _KB)
sys.path.insert(0, os.path.dirname(_KB))

from config import RAGConfig  # noqa: E402
from loader import build_index  # noqa: E402


def _resolve_spec(kb_chunks: list[dict], spec: dict) -> tuple[list[int], str]:
    """单个目标：章节 + 锚点 + 可选来源"""
    sec = spec.get("section") or ""
    anchors = [a.lower() for a in spec.get("anchors") or []]
    src = spec.get("source") or ""

    def secs(c):
        return c.get("sections") or ([c["section"]] if c.get("section") else [])

    by_section = [c for c in kb_chunks
                  if any(sec in s for s in secs(c))
                  and (not src or src in c.get("source", ""))]
    if not by_section:
        return [], "no_section_match"

    hit_all = [c for c in by_section
               if all(a in c["text"].lower() for a in anchors)]
    if hit_all:
        return [c["chunk_id"] for c in hit_all], "ok" if len(hit_all) <= 3 else "wide"

    partial = [c for c in by_section
               if any(a in c["text"].lower() for a in anchors)]
    if partial:
        return [c["chunk_id"] for c in partial], "partial"
    return [], "no_anchor_hit"


def resolve_one(kb_chunks: list[dict], q: dict) -> tuple[list[int], str]:
    """
    支持两种写法：
      单目标   section / anchors / source
      多目标   targets: [{section, anchors, source}, ...]   （跨文档题：两个证据都要找到）
    多目标时 gold = 各目标 chunk 的并集，另存 groups 以便评测"是否全部命中"。
    """
    specs = q.get("targets")
    if not specs:
        ids, st = _resolve_spec(kb_chunks, q)
        return ids, st

    groups, statuses = [], []
    for spec in specs:
        ids, st = _resolve_spec(kb_chunks, spec)
        groups.append(ids)
        statuses.append(st)
    q["_gold_groups"] = groups
    gold = sorted({i for g in groups for i in g})
    if all(s in ("ok", "wide") for s in statuses):
        return gold, "ok" if all(len(g) <= 3 for g in groups) else "wide"
    if any(s in ("partial", "ok", "wide") for s in statuses):
        return gold, "partial"
    return gold, "no_anchor_hit"


def main():
    ap = argparse.ArgumentParser(description="解析 gold chunk（离线）")
    ap.add_argument("--eval-set", default=os.path.join(_HERE, "eval_set_v2.json"))
    ap.add_argument("--config", default=os.path.join(_KB, "configs", "v2_tier1.json"))
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--show", type=int, default=0)
    args = ap.parse_args()

    cfg = RAGConfig.from_json(args.config)
    kb = build_index(cfg, verbose=False)
    chunks = kb["chunks"]
    by_id = {c["chunk_id"]: c for c in chunks}

    with open(args.eval_set, encoding="utf-8") as f:
        data = json.load(f)

    print(f"语料 {len(chunks)} 块 / 题目 {len(data['questions'])} 道\n")
    counts: dict[str, int] = {}
    for q in data["questions"]:
        gold, status = resolve_one(chunks, q)
        q["gold"] = gold
        q["gold_status"] = status
        counts[status] = counts.get(status, 0) + 1
        tag = {"ok": "✅", "wide": "⚠ ", "partial": "⚠ ", "no_section_match": "❌",
               "no_anchor_hit": "❌"}.get(status, "?")
        print(f"  {tag} Q{q['id']:<3} {len(gold):>2} 块 [{status:<16}] "
              f"{q['category']:<10} {q['question'][:36]}")

    print("\n" + "─" * 66)
    for k, v in sorted(counts.items()):
        print(f"  {k:<18} {v:>3} 题")
    bad = counts.get("no_section_match", 0) + counts.get("no_anchor_hit", 0)
    print(f"  {'需人工处理':<16} {bad:>3} 题")

    if args.show:
        print("\n" + "─" * 66)
        for q in data["questions"][:args.show]:
            if not q["gold"]:
                continue
            print(f"\nQ{q['id']} [{q['category']}] {q['question']}")
            for cid in q["gold"][:2]:
                c = by_id[cid]
                print(f"   #{cid} {c['source']} §{c['section'][:30]} ({c['char_len']}字)")
                print(f"      {c['text'][:120].replace(chr(10), ' ')}")

    if args.write:
        data["_resolved_at"] = __import__("time").strftime("%Y-%m-%d %H:%M:%S")
        data["_corpus_fp"] = (kb.get("meta") or {}).get("corpus_fp")
        with open(args.eval_set, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n已写回 {args.eval_set}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

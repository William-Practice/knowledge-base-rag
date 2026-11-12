"""
eval/run_eval.py — 跑一组配置，算检索指标 + 延迟，落 CSV

指标（只报相对差异，不宣称绝对泛化性 —— 见 AGENTS.md §3.4 报告纪律）
    hit@10        向量召回前 10 里是否含任一 gold
    hit@topn      整条流水线最终 top_n 里是否含任一 gold
    MRR@topn      第一个 gold 的倒数名次（未命中记 0）
    latency       分段计时 + 总时长（rerank 关掉时 rerank=0）

用法
    python eval/run_eval.py                                   # 基线：rewrite on + rerank on
    python eval/run_eval.py --no-rerank  --tag rerank_off
    python eval/run_eval.py --no-rewrite --tag rewrite_off
    python eval/run_eval.py --chunk-size 256 --tag chunk256   # 需先建对应索引
"""

import argparse
import csv
import json
import os
import statistics
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_KB = os.path.dirname(_HERE)
sys.path.insert(0, _KB)
sys.path.insert(0, os.path.dirname(_KB))

from config import DEFAULT_CONFIG, add_config_args, config_from_args  # noqa: E402


def pct(xs, p):
    if not xs:
        return 0.0
    s = sorted(xs)
    k = max(0, min(len(s) - 1, int(round((len(s) - 1) * p))))
    return s[k]


def main():
    ap = argparse.ArgumentParser(description="RAG 检索评测")
    add_config_args(ap)
    ap.add_argument("--eval-set", default=os.path.join(_HERE, "eval_set_v2.json"))
    ap.add_argument("--no-rerank", action="store_true")
    ap.add_argument("--no-rewrite", action="store_true", help="等价 --rewrite-mode off")
    ap.add_argument("--rewrite-mode", default=None,
                    choices=["off", "plain", "protected", "strict"])
    ap.add_argument("--decompose", action="store_true",
                    help="复合问题先拆成子问题，各自召回后用 RRF 融合")
    ap.add_argument("--max-sub", type=int, default=2, help="最多补几个子问题（原问题总是参与）")
    ap.add_argument("--top-n", type=int, default=None, help="最终保留条数（默认取 cfg.rerank_top_n）")
    ap.add_argument("--tag", default="baseline")
    ap.add_argument("--out-dir", default=os.path.join(_HERE, "results"))
    args = ap.parse_args()

    cfg = config_from_args(args)
    top_n = args.top_n if args.top_n is not None else cfg.rerank_top_n
    rw_mode = "off" if args.no_rewrite else (args.rewrite_mode or cfg.rewrite_mode)

    from loader import build_index
    from retriever import search, recall_multi, _rerank
    from generator import rewrite_query, missing_terms, decompose_query
    from embedding_utils import embed, cosine_similarity

    kb = build_index(cfg, verbose=False)
    chunks = kb["chunks"]
    with open(args.eval_set, encoding="utf-8") as f:
        qs = json.load(f)["questions"]
    qs = [q for q in qs if q.get("gold")]
    if not qs:
        print("❌ 评测集没有 gold，先跑 eval/resolve_gold.py --write")
        return 1

    print(f"配置 tag={args.tag}  chunk={cfg.chunk_size} recall_k={cfg.recall_k} "
          f"top_n={top_n} rerank={'off' if args.no_rerank else 'on'} "
          f"rewrite={rw_mode}")
    print(f"索引 {len(chunks)} 块 / 题目 {len(qs)} 道\n")

    rows, lat = [], {"rewrite": [], "decompose": [], "embed": [], "scan": [], "rerank": [], "total": []}
    for i, q in enumerate(qs, 1):
        gold = set(q["gold"])
        t0 = time.perf_counter()

        t = time.perf_counter()
        query = rewrite_query(q["question"], cfg=cfg, mode=rw_mode) if rw_mode != "off" else q["question"]
        lost = missing_terms(q["question"], query) if rw_mode != "off" else []
        lat["rewrite"].append(time.perf_counter() - t)

        subs = [query]
        if args.decompose:
            t = time.perf_counter()
            extra = decompose_query(q["question"], cfg=cfg, max_sub=args.max_sub)
            lat["decompose"].append(time.perf_counter() - t)
            # 原问题**永远**在检索集里：子问题写坏时由它兜底，
            # 保证「分解」不会比「不分解」更差（RRF 只是往候选池里加，不会删掉原有命中）
            seen, merged_q = set(), []
            for s in [query] + extra:
                k = s.strip()
                if k and k not in seen:
                    seen.add(k); merged_q.append(k)
            subs = merged_q

        if args.decompose:
            t = time.perf_counter()
            recalled = recall_multi(subs, kb, recall_k=cfg.recall_k, cfg=cfg)
            lat["scan"].append(time.perf_counter() - t)
        else:
            t = time.perf_counter()
            qvec = embed(query)
            lat["embed"].append(time.perf_counter() - t)

            t = time.perf_counter()
            scored = [(idx, cosine_similarity(qvec, c["vec"])) for idx, c in enumerate(chunks)]
            scored.sort(key=lambda x: x[1], reverse=True)
            recalled = []
            for rank, (idx, s) in enumerate(scored[:cfg.recall_k], 1):
                ch = dict(chunks[idx])
                ch["score"] = round(s, 4)
                ch["recall_rank"] = rank
                recalled.append(ch)
            lat["scan"].append(time.perf_counter() - t)

        t = time.perf_counter()
        if args.no_rerank:
            final = recalled[:top_n]
            applied = False
        else:
            final = _rerank(query, recalled, top_n=top_n, cfg=cfg)
            applied = bool(final) and all(c.get("rerank_applied") for c in final)
        lat["rerank"].append(time.perf_counter() - t)
        lat["total"].append(time.perf_counter() - t0)

        rec_ids = [c["chunk_id"] for c in recalled]
        fin_ids = [c["chunk_id"] for c in final]
        # 跨文档题：gold 由多个目标组成，额外统计"每个目标都被命中"（更严）
        groups = q.get("_gold_groups") or []
        all_targets = (all(any(cid in set(g) for cid in fin_ids[:top_n]) for g in groups)
                       if len(groups) > 1 else None)
        hit10 = any(cid in gold for cid in rec_ids[:10])
        hit_n = any(cid in gold for cid in fin_ids[:top_n])
        rr = 0.0
        for r, cid in enumerate(fin_ids[:top_n], 1):
            if cid in gold:
                rr = 1.0 / r
                break

        rows.append({
            "id": q["id"], "category": q["category"], "question": q["question"],
            "n_gold": len(gold), "hit@10": int(hit10), "hit@topn": int(hit_n),
            "rr": round(rr, 4), "rerank_applied": int(applied), "n_lost_terms": len(lost),
            "all_targets": ("" if all_targets is None else int(all_targets)),
            "n_targets": len(groups),
            "n_sub": len(subs),
            "gold_ids": "|".join(map(str, sorted(gold))),
            "top_ids": "|".join(map(str, fin_ids[:top_n])),
        })
        print(f"  [{i:>2}/{len(qs)}] Q{q['id']:<3} hit@10={int(hit10)} hit@{top_n}={int(hit_n)} "
              f"rr={rr:.2f}  {q['question'][:30]}")

    # ── 汇总 ──
    n = len(rows)
    m_hit10 = sum(r["hit@10"] for r in rows) / n
    m_hitn = sum(r["hit@topn"] for r in rows) / n
    m_mrr = sum(r["rr"] for r in rows) / n
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)

    print("\n" + "═" * 62)
    print(f"{args.tag:<22} hit@10={m_hit10:.3f}  hit@{top_n}={m_hitn:.3f}  MRR@{top_n}={m_mrr:.3f}")
    for cat, rs in sorted(by_cat.items()):
        print(f"  {cat:<12} n={len(rs):<3} hit@10={sum(x['hit@10'] for x in rs)/len(rs):.3f}"
              f"  hit@{top_n}={sum(x['hit@topn'] for x in rs)/len(rs):.3f}"
              f"  MRR={sum(x['rr'] for x in rs)/len(rs):.3f}")
    multi_rows = [r for r in rows if r["n_targets"] > 1]
    if multi_rows:
        cov = sum(r["all_targets"] for r in multi_rows) / len(multi_rows)
        print(f"  跨文档题全目标覆盖：{cov:.3f}（{len(multi_rows)} 题，n_targets>1）")
    lost_total = sum(r["n_lost_terms"] for r in rows)
    print(f"  改写丢失受保护词：{lost_total} 次")
    if not args.no_rerank:
        applied = sum(r["rerank_applied"] for r in rows)
        print(f"  rerank 实际生效：{applied}/{n}" + ("  ⚠ 有未生效的题" if applied < n else ""))

    print(f"\n{'阶段':<10}{'中位(s)':>9}{'P95(s)':>9}")
    for k in ("rewrite", "decompose", "embed", "scan", "rerank", "total"):
        if not lat.get(k):
            continue
        print(f"{k:<10}{statistics.median(lat[k]):>9.3f}{pct(lat[k], 0.95):>9.3f}")

    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir, f"{args.tag}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\n明细 → {out}")

    summary_path = os.path.join(args.out_dir, "summary.csv")
    new = not os.path.exists(summary_path)
    with open(summary_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["tag", "chunk_size", "recall_k", "top_n", "rerank", "rewrite",
                        "n", "hit@10", "hit@topn", "mrr", "p50_total_s", "p95_total_s"])
        w.writerow([args.tag, cfg.chunk_size, cfg.recall_k, top_n,
                    int(not args.no_rerank), int(not args.no_rewrite), n,
                    round(m_hit10, 4), round(m_hitn, 4), round(m_mrr, 4),
                    round(statistics.median(lat["total"]), 4), round(pct(lat["total"], 0.95), 4)])
    print(f"汇总 → {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
bench/probe_baseline.py — P0 基线探针：量出每个阶段的真实耗时并落档

为什么要它
    改造前必须先有"改造前"。没有基线，后面所有"快了 N 倍"都是空话。
    本脚本把一次问答拆成 5 段分别计时，落成 JSON，供改造后对照。

用法
    # 只测本地检索（离线，不调 API，不花额度）
    python bench/probe_baseline.py --dry-run

    # 全链路（需要智谱余额）
    python bench/probe_baseline.py --queries 5 --out bench/baseline-20261106.json

输出
    stdout 表格（每阶段 min/中位/max）+ JSON 档案
"""

import argparse
import json
import os
import statistics
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_KB = os.path.dirname(_HERE)
sys.path.insert(0, _KB)

from config import DEFAULT_CONFIG, add_config_args, config_from_args  # noqa: E402


def _load_queries(path: str, n: int) -> list[str]:
    if not os.path.exists(path):
        return ["Kafka 中 ISR 是什么？Leader 和 Follower 是如何工作的？"]
    with open(path, encoding="utf-8") as f:
        qs = json.load(f)["questions"]
    return [q["question"] for q in qs][:n]


def _stats(xs: list[float]) -> dict:
    if not xs:
        return {}
    return {
        "n": len(xs),
        "min": round(min(xs), 4),
        "p50": round(statistics.median(xs), 4),
        "max": round(max(xs), 4),
        "mean": round(statistics.fmean(xs), 4),
    }


def load_kb(cfg, allow_stale: bool):
    """allow_stale: 直接读现有 JSON（旧格式也行），用于离线测本地检索"""
    from loader import build_index
    if allow_stale and os.path.exists(cfg.store_path()):
        t = time.perf_counter()
        with open(cfg.store_path(), encoding="utf-8") as f:
            kb = json.load(f)
        return kb, round(time.perf_counter() - t, 4)
    t = time.perf_counter()
    kb = build_index(cfg)
    return kb, round(time.perf_counter() - t, 4)


def main():
    p = argparse.ArgumentParser(description="RAG 各阶段耗时基线探针")
    add_config_args(p)
    p.add_argument("--queries", type=int, default=5, help="抽样题数")
    p.add_argument("--eval-set", default=os.path.join(_KB, "eval_set.json"))
    p.add_argument("--out", default=None, help="结果 JSON 路径")
    p.add_argument("--dry-run", action="store_true",
                   help="只测本地检索（离线，不调 API）")
    args = p.parse_args()

    cfg = config_from_args(args)
    queries = _load_queries(args.eval_set, args.queries)

    print("═" * 62)
    print(f"基线探针  chunk={cfg.chunk_size} overlap={cfg.chunk_overlap} "
          f"recall_k={cfg.recall_k} top_n={cfg.rerank_top_n}")
    print(f"模型      embed={cfg.embed_model} rerank={cfg.rerank_model} llm={cfg.llm_model}")
    print(f"模式      {'dry-run（仅本地）' if args.dry_run else '全链路'}")
    print("═" * 62)

    kb, load_secs = load_kb(cfg, allow_stale=args.dry_run)
    chunks = kb.get("chunks", [])
    print(f"索引      {len(chunks)} 块 / 加载或建库 {load_secs:.2f}s\n")

    if not chunks:
        print("❌ 索引为空，先跑 loader.py")
        return 1

    rows = []
    for i, q in enumerate(queries, 1):
        row = {"question": q}
        print(f"[{i}/{len(queries)}] {q}")

        if args.dry_run:
            # 本地向量扫描：用已有 chunk 向量代替 query 向量，只量扫描开销
            from embedding_utils import search_with_vectors
            qvec = chunks[0]["vec"]
            cands = [(c["text"], c["vec"]) for c in chunks]
            for _ in range(3):  # 预热
                search_with_vectors(qvec, cands, top_n=cfg.recall_k)
            ts = []
            for _ in range(10):
                t = time.perf_counter()
                search_with_vectors(qvec, cands, top_n=cfg.recall_k)
                ts.append(time.perf_counter() - t)
            row["vector_scan"] = round(statistics.median(ts), 4)
            print(f"   本地向量扫描  中位 {row['vector_scan']*1000:.1f} ms")
        else:
            from generator import rewrite_query, answer
            from retriever import _rerank
            from embedding_utils import embed, search_with_vectors

            t = time.perf_counter()
            rewritten = rewrite_query(q, cfg=cfg)
            row["rewrite"] = round(time.perf_counter() - t, 4)

            t = time.perf_counter()
            qvec = embed(rewritten)
            row["query_embed"] = round(time.perf_counter() - t, 4)

            cands = [(c["text"], c["vec"]) for c in chunks]
            t = time.perf_counter()
            recalled = search_with_vectors(qvec, cands, top_n=cfg.recall_k)
            row["vector_scan"] = round(time.perf_counter() - t, 4)

            text_to_chunk = {c["text"]: c for c in chunks}
            cand_chunks = [dict(text_to_chunk[txt]) for txt, _ in recalled]
            t = time.perf_counter()
            top = _rerank(rewritten, cand_chunks, cfg=cfg)
            row["rerank"] = round(time.perf_counter() - t, 4)

            t = time.perf_counter()
            ans, _src = answer(q, top, cfg=cfg)
            row["generate"] = round(time.perf_counter() - t, 4)
            row["answer_chars"] = len(ans)

            row["total"] = round(sum(row.get(k, 0) for k in
                                     ("rewrite", "query_embed", "vector_scan",
                                      "rerank", "generate")), 4)
            print(f"   rewrite {row['rewrite']*1000:6.0f} ms | embed {row['query_embed']*1000:6.0f} ms | "
                  f"scan {row['vector_scan']*1000:6.1f} ms")
            print(f"   rerank  {row['rerank']*1000:6.0f} ms | gen   {row['generate']*1000:6.0f} ms | "
                  f"合计 {row['total']*1000:6.0f} ms")

        rows.append(row)

    # ── 汇总 ──
    phases = ["rewrite", "query_embed", "vector_scan", "rerank", "generate", "total"]
    summary = {ph: _stats([r[ph] for r in rows if ph in r]) for ph in phases}
    summary = {k: v for k, v in summary.items() if v}

    print("\n" + "═" * 62)
    print(f"{'阶段':<14}{'min(s)':>9}{'中位(s)':>10}{'max(s)':>9}   占比")
    total_p50 = summary.get("total", {}).get("p50") or 0
    for ph in phases:
        if ph not in summary or ph == "total":
            continue
        s = summary[ph]
        share = f"{s['p50']/total_p50*100:5.1f}%" if total_p50 else "    —"
        print(f"{ph:<14}{s['min']:>9.3f}{s['p50']:>10.3f}{s['max']:>9.3f}   {share}")
    if "total" in summary:
        print("-" * 62)
        print(f"{'全链路':<14}{summary['total']['min']:>9.3f}"
              f"{summary['total']['p50']:>10.3f}{summary['total']['max']:>9.3f}")
    print("═" * 62)

    out = args.out or os.path.join(
        _HERE, f"baseline-{time.strftime('%Y%m%d-%H%M')}.json")
    payload = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "dry-run" if args.dry_run else "full",
        "config": cfg.as_dict(),
        "index": {"chunks": len(chunks),
                  "doc_count": kb.get("doc_count"),
                  "corpus_fp": (kb.get("meta") or {}).get("corpus_fp"),
                  "load_or_build_seconds": load_secs},
        "rows": rows,
        "summary": summary,
    }
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"已落档 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

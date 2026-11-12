"""
retriever.py — ③ 检索层：向量召回 TopK → Rerank 精排 TopN

P1 改造（2026-11-08）
① 全程用 **chunk 下标** 传递，不再拿 text 当字典键
   实测：457 块里有 2 组重复文本（4 块）。用 text 回查时后者覆盖前者，
   rerank 结果会静默映射到另一个 chunk，评测数字随之失真。
② 去掉 `chunks[0]` 兜底。映射不上就抛异常 —— 静默返回第一段是最坏的失败模式，
   因为它看起来完全正常。
③ 结果带 `rerank_applied`。recall_k <= rerank_top_n 时精排会短路，
   这时若还当作"已 rerank"去跑消融，测出来的其实是 rerank off。
"""

import json
import re
import urllib.request
import warnings

from config import *                      # RERANK_URL / LLM_API_KEY / 旧常量名
from config import DEFAULT_CONFIG, RAGConfig
from embedding_utils import embed, cosine_similarity


def _call_rerank_api(query: str, documents: list[str], top_n: int,
                     cfg: RAGConfig) -> list[dict]:
    """调智谱 rerank，归一成 [{"index": int|None, "score": float, "document": str|None}]"""
    body = json.dumps({
        "model": cfg.rerank_model,
        "query": query,
        "documents": documents,
        "top_n": top_n,
    }).encode("utf-8")

    req = urllib.request.Request(
        RERANK_URL, data=body,
        headers={
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results = data.get("results") or data.get("data") or []
    if not results:
        raise RuntimeError(f"rerank 返回空结果：{str(data)[:200]}")

    out = []
    for r in results:
        score = r.get("relevance_score", r.get("score"))
        if score is None:
            raise RuntimeError(f"rerank 结果缺少分数字段：{str(r)[:200]}")
        out.append({
            "index": r.get("index"),
            "score": float(score),
            "document": r.get("document"),
        })
    return out


def _rerank(query: str, chunks: list[dict], top_n: int | None = None,
            cfg: RAGConfig = DEFAULT_CONFIG) -> list[dict]:
    """按 query 相关性精排。返回的每块都带 rerank_applied（True/False）。"""
    top_n = cfg.rerank_top_n if top_n is None else top_n
    if not chunks:
        return []

    # 候选本来就少于目标条数 → 无需精排。但必须让调用方知道"这次没精排"
    if len(chunks) <= top_n:
        return [{**c, "rerank_applied": False} for c in chunks]

    raw = _call_rerank_api(query, [c["text"] for c in chunks], top_n, cfg)

    # 同一内容可能出现多次：按出现顺序逐个消费，避免两个结果映射到同一块。
    # 键用「空白归一化」后的文本 —— 实测 rerank-pro 只返回 document 不返回 index，
    # 且 CRLF / 多余空格可能被服务端改写，严格相等会误判为"找不到"。
    def _key(t: str) -> str:
        return re.sub(r"\s+", " ", t).strip()

    by_text: dict[str, list[int]] = {}
    for i, c in enumerate(chunks):
        by_text.setdefault(_key(c["text"]), []).append(i)

    out, seen = [], set()
    for item in raw:
        if item["index"] is not None:
            i = int(item["index"])
            if not 0 <= i < len(chunks):
                raise RuntimeError(
                    f"rerank 返回越界下标 {i}（候选共 {len(chunks)} 条）")
        else:
            doc = item["document"] or ""
            bucket = by_text.get(_key(doc))
            if not bucket:
                raise RuntimeError(
                    "rerank 返回的 document 在候选中找不到（无法映射到 chunk）；"
                    f"首 40 字={doc[:40]!r}")
            i = bucket.pop(0)

        if i in seen:
            continue
        seen.add(i)
        ch = dict(chunks[i])
        ch["rerank_score"] = round(item["score"], 4)
        ch["rerank_applied"] = True
        ch["_idx"] = i
        out.append(ch)

    if not out:
        raise RuntimeError("rerank 结果全部无法映射到候选 chunk")

    # 按 API 返回顺序（rerank-pro 自己按分数降序）；它可能忽略 top_n 返回全部，这里截断
    return out[:top_n]


def search(query: str, kb: dict, recall_k: int | None = None,
           rerank_top_n: int | None = None,
           cfg: RAGConfig = DEFAULT_CONFIG) -> list[dict]:
    """
    检索主流程：向量召回 TopK → Rerank 精排 TopN

    :param kb: build_index() 返回的 {"chunks": [...]}
    :return: [{chunk_id, source, section, offset, text, score(召回分),
               recall_rank, rerank_score?, rerank_applied}]
    """
    recall_k = cfg.recall_k if recall_k is None else recall_k
    rerank_top_n = cfg.rerank_top_n if rerank_top_n is None else rerank_top_n
    chunks = kb.get("chunks", [])
    if not chunks:
        return []

    if recall_k <= rerank_top_n:
        warnings.warn(
            f"recall_k({recall_k}) <= rerank_top_n({rerank_top_n})：精排会短路，"
            "结果等同于 rerank off。跑消融时这会让 on/off 两组变成同一组。",
            RuntimeWarning, stacklevel=2)

    # ① 向量召回 —— 按下标建结果，不用 text 做键
    q_vec = embed(query)
    scored = [(i, cosine_similarity(q_vec, c["vec"])) for i, c in enumerate(chunks)]
    scored.sort(key=lambda x: x[1], reverse=True)

    recalled = []
    for rank, (i, score) in enumerate(scored[:recall_k], 1):
        ch = dict(chunks[i])
        ch["score"] = round(score, 4)
        ch["recall_rank"] = rank
        ch["_idx"] = i
        recalled.append(ch)

    # ② Rerank 精排
    return _rerank(query, recalled, top_n=rerank_top_n, cfg=cfg)


def recall_multi(sub_queries: list[str], kb: dict, recall_k: int | None = None,
                 rrf_k: int = 60, cfg: RAGConfig = DEFAULT_CONFIG) -> list[dict]:
    """多子查询召回 + RRF 融合，返回**精排前**的候选列表（供评测计算 hit@k）"""
    recall_k = cfg.recall_k if recall_k is None else recall_k
    chunks = kb.get("chunks", [])
    if not chunks:
        return []

    lists: list[list[int]] = []
    for sub in sub_queries:
        qv = embed(sub)
        scored = sorted(((i, cosine_similarity(qv, c["vec"]))
                         for i, c in enumerate(chunks)), key=lambda x: -x[1])
        lists.append([i for i, _ in scored[:recall_k]])

    if len(lists) == 1:
        return [dict(chunks[i], score=1.0, recall_rank=r, _idx=i)
                for r, i in enumerate(lists[0], 1)]

    agg: dict[int, float] = {}
    for lst in lists:
        for rank, idx in enumerate(lst, 1):
            agg[idx] = agg.get(idx, 0.0) + 1.0 / (rrf_k + rank)
    merged = sorted(agg.items(), key=lambda kv: -kv[1])[:recall_k]
    return [dict(chunks[i], score=round(s, 6), recall_rank=r, _idx=i)
            for r, (i, s) in enumerate(merged, 1)]


def search_multi(query: str, kb: dict, sub_queries: list[str] | None = None,
                 recall_k: int | None = None, rerank_top_n: int | None = None,
                 rrf_k: int = 60, cfg: RAGConfig = DEFAULT_CONFIG) -> list[dict]:
    """
    多子查询检索：每个子问题独立召回，用 RRF 融合，再用**原问题**精排。

    为什么用 RRF 而不是加权分数：不同子问题的余弦分数量纲不可比，
    但名次可比。RRF 只用名次，不需要调权重。

    子问题只有 1 个时，行为与 search() 一致（便于 A/B 对照）。
    """
    recall_k = cfg.recall_k if recall_k is None else recall_k
    top_n = cfg.rerank_top_n if rerank_top_n is None else rerank_top_n
    chunks = kb.get("chunks", [])
    if not chunks:
        return []

    recalled = recall_multi(sub_queries or [query], kb, recall_k=recall_k, rrf_k=rrf_k, cfg=cfg)
    return _rerank(query, recalled, top_n=top_n, cfg=cfg)


if __name__ == "__main__":
    from loader import build_index
    kb = build_index()
    q = "Kafka 的分区副本是怎么工作的？"
    print(f"\n查询: {q}\n")
    for i, c in enumerate(search(q, kb), 1):
        print(f"  #{i} recall={c['score']} rerank={c.get('rerank_score')} "
              f"applied={c.get('rerank_applied')} "
              f"[{c['source']} §{c.get('section','?')[:18]} #{c['chunk_id']}]")
        print(f"     {c['text'][:80].replace(chr(10), ' ')}")

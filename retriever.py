"""
retriever.py — ③ 检索层：向量召回 Top10 → Rerank 精排 Top3
向量检索复用 embedding_utils；Rerank 调智谱 rerank-pro API
"""

import json
import urllib.request

from config import *
from embedding_utils import embed, search_with_vectors


def _rerank(query: str, chunks: list[dict], top_n: int = RERANK_TOP_N) -> list[dict]:
    """调智谱 Rerank API：按 query 相关性给 chunks 精排，返回 top_n"""
    if not chunks:
        return []
    if len(chunks) <= top_n:
        return chunks

    documents = [c["text"] for c in chunks]
    body = json.dumps({
        "model": RERANK_MODEL,
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

    reranked = []
    text_to_chunk = {c["text"]: c for c in chunks}
    for r in data.get("results", []):
        if "index" in r:
            idx = r["index"]
            chunk = dict(chunks[idx])
        else:
            # rerank-pro 返回 document 文本而非 index，按文本回查
            chunk = dict(text_to_chunk.get(r.get("document", ""), chunks[0]))
        chunk["rerank_score"] = round(r["relevance_score"], 4)
        reranked.append(chunk)
    # rerank-pro 可能忽略 top_n 返回全部，客户端截断（返回按分数降序）
    return reranked[:top_n]


def search(query: str, kb: dict, recall_k: int = RECALL_K,
           rerank_top_n: int = RERANK_TOP_N) -> list[dict]:
    """
    检索主流程：向量召回 TopK → Rerank 精排 TopN
    :param kb: build_index() 返回的 {"chunks": [...]}
    :return: [{"chunk_id", "source", "text", "vec", "score"(召回分), "rerank_score"}, ...]
    """
    chunks = kb.get("chunks", [])
    if not chunks:
        return []

    # ① 向量召回
    q_vec = embed(query)
    candidates = [(c["text"], c["vec"]) for c in chunks]
    recalled = search_with_vectors(q_vec, candidates, top_n=recall_k)

    # 按 text 回查 chunk
    text_to_chunk = {c["text"]: c for c in chunks}
    recalled_chunks = []
    for text, score in recalled:
        chunk = dict(text_to_chunk[text])
        chunk["score"] = round(score, 4)
        recalled_chunks.append(chunk)

    # ② Rerank 精排
    reranked = _rerank(query, recalled_chunks, top_n=rerank_top_n)
    return reranked


if __name__ == "__main__":
    from loader import build_index
    kb = build_index()
    q = "Kafka 的分区副本是怎么工作的？"
    print(f"\n查询: {q}\n")
    for i, c in enumerate(search(q, kb), 1):
        print(f"  #{i} rerank={c.get('rerank_score')} [{c['source']} chunk {c['chunk_id']}]")
        print(f"     {c['text'][:80].replace(chr(10), ' ')}")

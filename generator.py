"""
generator.py — ④ 生成层：Query 重写 + 拼 Prompt + GLM 生成（答案 + 来源）
纯 HTTP/JSON 调用 GLM
"""

import json
import urllib.request

from config import *                      # LLM_BASE_URL / LLM_API_KEY
from config import DEFAULT_CONFIG, RAGConfig
from retriever import search


def _glm_chat(prompt: str, temperature: float | None = None, model: str | None = None,
              cfg: RAGConfig = DEFAULT_CONFIG) -> str:
    temperature = cfg.temperature if temperature is None else temperature
    model = cfg.llm_model if model is None else model
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{LLM_BASE_URL}chat/completions", data=body,
        headers={
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def rewrite_query(question: str, cfg: RAGConfig = DEFAULT_CONFIG) -> str:
    """把口语问题改写成适合文档检索的书面问题（补全代词、规范表述）"""
    prompt = f"""把下面口语问题改写成适合文档检索的清晰问题。
要求：补全代词、改书面语、保留原意，只输出改写后的问题，不要其他内容。

问题：{question}
改写："""
    return _glm_chat(prompt, temperature=0.1, cfg=cfg)


def answer(query: str, docs: list[dict],
           cfg: RAGConfig = DEFAULT_CONFIG) -> tuple[str, list[dict]]:
    """拼 context + 生成答案，返回 (答案, 来源列表)"""
    context = "\n\n".join(
        f"[{c.get('source', '?')} 片段{c.get('chunk_id', '?')}]\n{c['text']}"
        for c in docs
    )

    prompt = f"""你是严谨的助教。只根据【参考资料】回答用户问题。
资料中没有的内容，明确说"笔记里没提到"，不要编造。

【参考资料】
{context}

【问题】{query}

【回答】"""
    ans = _glm_chat(prompt, temperature=cfg.temperature, cfg=cfg)

    sources = [{
        "file": c.get("source", "?"),
        "chunk": c.get("chunk_id", "?"),
        "score": c.get("rerank_score", c.get("score", "?")),
        "snippet": c["text"][:60] + "...",
    } for c in docs]

    return ans, sources


def full_answer(question: str, kb: dict,
                cfg: RAGConfig = DEFAULT_CONFIG) -> dict:
    """一键问答：重写 → 检索 → 生成，返回结构化结果"""
    rewritten = rewrite_query(question, cfg=cfg)
    docs = search(rewritten, kb, cfg=cfg)
    ans, sources = answer(question, docs, cfg=cfg)
    return {
        "question": question,
        "rewritten": rewritten,
        "answer": ans,
        "sources": sources,
    }


if __name__ == "__main__":
    from loader import build_index
    from retriever import search

    kb = build_index()
    q = "Kafka 的 LEO 和 HW 是什么？"
    result = full_answer(q, kb)
    print(f"原问题: {q}")
    print(f"重写后: {result['rewritten']}\n")
    print(f"答案: {result['answer']}\n")
    print("来源:")
    for s in result["sources"]:
        print(f"  {s}")

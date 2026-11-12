"""
generator.py — ④ 生成层：Query 重写 + 拼 Prompt + GLM 生成（答案 + 来源）
纯 HTTP/JSON 调用 GLM
"""

import json
import re
import urllib.request
import warnings

from config import *                      # LLM_BASE_URL / LLM_API_KEY
from config import DEFAULT_CONFIG, RAGConfig
from retriever import search

# 改写时必须原样保留的"技术记号"：英文单词 / 文件名 / 配置键 / 命令行参数。
# 中文问题里出现的 ASCII token 几乎都是实体（Kafka、ISR、mapred-site.xml、--to-earliest），
# 而实测 plain rewrite 恰恰会动它们：mapred-site.xml → mapreduce-site.xml。
_PROTECTED = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]{1,}")


def protected_terms(question: str) -> list[str]:
    return sorted({m.group(0) for m in _PROTECTED.finditer(question)})


def missing_terms(question: str, rewritten: str) -> list[str]:
    """改写后没能保留下来的受保护词（大小写不敏感）"""
    low = rewritten.lower()
    return [t for t in protected_terms(question) if t.lower() not in low]


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


def rewrite_query(question: str, cfg: RAGConfig = DEFAULT_CONFIG,
                  mode: str | None = None) -> str:
    """
    把口语问题改写成书面问题。四种模式（实测结论见 AGENTS.md §8.2）：

      off       直接返回原问题（不调 LLM，结果确定）
      plain     原实现：纯 LLM 改写。**实测是负收益**——会改坏文件名和实体
      protected 改写 + 把丢失的受保护词补回查询末尾
      strict    改写结果只要丢了任一受保护词，就整体作废退回原问题
    """
    mode = (mode or getattr(cfg, "rewrite_mode", "plain")).lower()
    if mode == "off":
        return question

    terms = protected_terms(question)
    # 只有 protected / strict 才加守卫。plain 保持原实现（无守卫），
    # 否则它也会被顺带修好，历史数字就不可比了 —— 实测正是如此。
    guard = ""
    if mode in ("protected", "strict") and terms:
        guard = "\n必须原样保留下列术语，不许翻译、改写、纠错、补全：" + "、".join(terms)
    prompt = f"""把下面口语问题改写成适合文档检索的清晰问题。
要求：补全代词、改书面语、保留原意，只输出改写后的问题，不要其他内容。{guard}

问题：{question}
改写："""
    out = _glm_chat(prompt, temperature=0.1, cfg=cfg)

    if mode == "plain":
        return out

    lost = missing_terms(question, out)
    if mode == "protected":
        return out if not lost else f"{out} {' '.join(lost)}"

    if mode == "strict":
        if lost:
            warnings.warn(f"改写丢失受保护词 {lost}，退回原问题", RuntimeWarning, stacklevel=2)
            return question
        return out

    raise ValueError(f"未知 rewrite_mode: {mode}（可选 off/plain/protected/strict）")


_DECOMP_PROMPT = """把下面这个问题拆成可以独立检索的子问题，最多 {n} 个。

规则：
1. **只在问题确实包含两个及以上独立信息需求时才拆。** 只问一件事就原样输出一行，
   不要为了凑数量而拆。
2. 每个子问题必须**脱离上下文也能读懂**：不得出现"它/这个/该/上面"这类代词，
   需要指代时把原词补全（例：把"它和 Rebalance 什么关系"写成"Kafka 的 Lag 和 Rebalance 什么关系"）。
3. 子问题之间不得互相重复，也不要输出"分别是什么"这类要再拆一次的问题。
4. 必须原样保留技术名词、文件名、配置项、命令（不得翻译、不得改写、不得补全）。
5. 每行一个子问题，不要编号、不要解释、不要额外文字。

问题：{q}
子问题："""


def decompose_query(question: str, cfg: RAGConfig = DEFAULT_CONFIG,
                    max_sub: int = 2) -> list[str]:
    """
    把复合问题拆成可独立检索的子问题。

    为什么要拆：一个 chunk 装不下两处事实，单轮检索对跨文档题几乎必然漏一半
    （实测 60 题里跨文档全目标覆盖只有 0.235）。

    安全网：
      · 受保护词（文件名/命令/参数名）必须在输出里出现，否则退回原问题
      · 输出超过 max_sub 行只取前 max_sub
      · 任何异常一律退回 [question] —— 分解失败不能比不分解更差
    """
    try:
        out = _glm_chat(_DECOMP_PROMPT.format(n=max_sub, q=question),
                        temperature=0.0, cfg=cfg)
    except Exception:
        return [question]

    lines = []
    for raw in out.splitlines():
        line = raw.strip()
        line = re.sub(r'^[-*•\d]+[.、)\s]*', '', line).strip()   # 去编号/项目符号
        if len(line) >= 4:
            lines.append(line)
    if not lines:
        return [question]

    joined = " ".join(lines).lower()
    lost = [t for t in protected_terms(question) if t.lower() not in joined]
    if lost:
        warnings.warn(f"分解丢失受保护词 {lost}，退回原问题", RuntimeWarning, stacklevel=2)
        return [question]

    return lines[:max_sub]


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

"""
api.py — ⑤ 服务层：FastAPI 把「重写 → 检索 → 生成」变成 HTTP 接口

启动（在 knowledge_base/ 目录下）：
    /data/Projects/GLMModelsDemo/helloGLM/bin/python -m uvicorn api:app --reload --port 8000

浏览器打开 http://localhost:8000/docs 看接口文档
"""

import os

from fastapi import FastAPI
from pydantic import BaseModel

from config import DEFAULT_CONFIG, RAGConfig
from loader import build_index
from retriever import search
from generator import rewrite_query, answer

# 配置注入：KB_CONFIG=<json 路径> 可整体替换参数（消融实验 / 多套索引共存）
CFG = RAGConfig.from_json(os.environ["KB_CONFIG"]) if os.environ.get("KB_CONFIG") else DEFAULT_CONFIG

app = FastAPI(
    title="个人知识库问答系统",
    description="5 层架构 RAG：Query重写 → 向量召回 → Rerank精排 → GLM生成",
    version="1.1.0",
)

# 启动时建库一次（已存在且指纹匹配则直接加载）
kb = build_index(CFG)


class AskRequest(BaseModel):
    question: str


@app.get("/health")
def health():
    """健康检查"""
    meta = kb.get("meta") or {}
    return {
        "status": "ok",
        "msg": "知识库问答服务在线",
        "chunks": kb.get("chunk_count", 0),
        "docs": kb.get("doc_count", 0),
        "corpus_fp": meta.get("corpus_fp"),
        "built_at": meta.get("built_at"),
        "config": CFG.as_dict(),
    }


@app.post("/ask")
def ask(req: AskRequest):
    """全链路问答：Query重写 → 检索(Rerank) → 生成"""
    # ① Query 重写（补全代词/规范表述）
    rewritten = rewrite_query(req.question, cfg=CFG)

    # ② 检索：向量召回 Top10 + Rerank Top3
    docs = search(rewritten, kb, cfg=CFG)

    # ③ 生成：拼 context + GLM，返回答案与来源
    ans, sources = answer(req.question, docs, cfg=CFG)

    return {
        "question": req.question,
        "rewritten": rewritten,
        "answer": ans,
        "sources": sources,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

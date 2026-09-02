"""
api.py — ⑤ 服务层：FastAPI 把「重写 → 检索 → 生成」变成 HTTP 接口

启动（在 knowledge_base/ 目录下）：
    /data/Projects/GLMModelsDemo/helloGLM/bin/python -m uvicorn api:app --reload --port 8000

浏览器打开 http://localhost:8000/docs 看接口文档
"""

from fastapi import FastAPI
from pydantic import BaseModel

from loader import build_index
from retriever import search
from generator import rewrite_query, answer

app = FastAPI(
    title="个人知识库问答系统",
    description="5 层架构 RAG：Query重写 → 向量召回 → Rerank精排 → GLM生成",
    version="1.0.0",
)

# 启动时建库一次（已存在则直接加载）
kb = build_index()


class AskRequest(BaseModel):
    question: str


@app.get("/health")
def health():
    """健康检查"""
    return {
        "status": "ok",
        "msg": "知识库问答服务在线",
        "chunks": kb.get("chunk_count", 0),
        "docs": kb.get("doc_count", 0),
    }


@app.post("/ask")
def ask(req: AskRequest):
    """全链路问答：Query重写 → 检索(Rerank) → 生成"""
    # ① Query 重写（补全代词/规范表述）
    rewritten = rewrite_query(req.question)

    # ② 检索：向量召回 Top10 + Rerank Top3
    docs = search(rewritten, kb)

    # ③ 生成：拼 context + GLM，返回答案与来源
    ans, sources = answer(req.question, docs)

    return {
        "question": req.question,
        "rewritten": rewritten,
        "answer": ans,
        "sources": sources,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

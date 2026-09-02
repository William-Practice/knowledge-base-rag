"""
loader.py — ② 数据层：加载 docs/ 多文档 → 切分 → 向量化 → 持久化建库
数据落盘在 kb_store/（JSON + 向量），复用 embedding_utils
"""

import os
import glob

from config import *
from embedding_utils import embed


def load_files(docs_dir: str = DOCS_DIR) -> list[dict]:
    """加载 docs/ 下所有 txt/md 文档 → [{"source": 文件名, "text": 全文}]"""
    files = glob.glob(os.path.join(docs_dir, "*.txt")) + \
            glob.glob(os.path.join(docs_dir, "*.md"))
    docs = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                text = fh.read().strip()
            if text:
                docs.append({"source": os.path.basename(f), "text": text})
        except Exception as e:
            print(f"  ⚠ 跳过 {os.path.basename(f)}: {e}")
    return docs


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> list[str]:
    """按段落 + 字符数切分，带重叠"""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    buf = ""
    for p in paragraphs:
        if len(buf) + len(p) < chunk_size:
            buf += p + "\n"
        else:
            if buf:
                chunks.append(buf.strip())
            overlap_text = buf[-overlap:] if len(buf) > overlap else buf
            buf = overlap_text + "\n" + p + "\n"
    if buf:
        chunks.append(buf.strip())
    return chunks


def build_index(force: bool = False) -> dict:
    """
    加载 + 切分 + 向量化 + 持久化建库
    :return: {"chunks": [...], "doc_count": N, "chunk_count": M}
    """
    store_path = os.path.join(PERSIST_DIR, f"{KB_NAME}.json")
    if not force and os.path.exists(store_path):
        print(f"✅ 加载已有向量库：{store_path}")
        import json
        with open(store_path, encoding="utf-8") as f:
            data = json.load(f)
        return data

    docs = load_files()
    if not docs:
        print("⚠ docs/ 下没有可加载的文档")
        return {"chunks": [], "doc_count": 0, "chunk_count": 0}

    chunks = []
    for doc in docs:
        parts = chunk_text(doc["text"])
        for i, part in enumerate(parts):
            chunks.append({
                "chunk_id": len(chunks) + 1,
                "source": doc["source"],
                "text": part,
            })

    print(f"切分完成：{len(docs)} 个文件 → {len(chunks)} 个片段，开始向量化...")

    for i, c in enumerate(chunks):
        c["vec"] = embed(c["text"])
        if (i + 1) % 10 == 0 or i == len(chunks) - 1:
            print(f"  向量化进度: {i+1}/{len(chunks)}")

    os.makedirs(PERSIST_DIR, exist_ok=True)
    import json
    with open(store_path, "w", encoding="utf-8") as f:
        json.dump({"chunks": chunks, "doc_count": len(docs),
                   "chunk_count": len(chunks)}, f, ensure_ascii=False)

    print(f"✅ 建库完成：{len(chunks)} 个片段，来自 {len(docs)} 个文件 → {store_path}")
    return {"chunks": chunks, "doc_count": len(docs), "chunk_count": len(chunks)}


if __name__ == "__main__":
    build_index()

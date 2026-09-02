"""
config.py — ① 配置层：所有模型/路径/参数集中管理
换模型只改这里，不动业务代码
"""

import os
import sys

# 让 knowledge_base/ 能 import 上层项目模块（embedding_utils 等）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def load_env(path: str | None = None):
    """极简 .env 加载器（无第三方依赖）"""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env()

# === 模型配置（智谱 GLM） ===
LLM_MODEL = os.getenv("GLM_MODEL", "glm-4v-flash")          # 生成模型
LLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
LLM_API_KEY = os.getenv("ZHIPU_API_KEY", "")
if not LLM_API_KEY:
    raise ValueError("缺少 ZHIPU_API_KEY，请在 .env 或环境变量中设置")

# === Embedding（智谱 embedding-2，1024 维） ===
EMBED_MODEL = "embedding-2"
EMBED_DIM = 1024

# === Rerank（智谱 rerank-pro） ===
RERANK_URL = "https://open.bigmodel.cn/api/paas/v4/rerank"
RERANK_MODEL = "rerank-pro"

# === RAG 参数 ===
DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
CHUNK_SIZE = 500              # 切分块大小（字符）
CHUNK_OVERLAP = 50            # 块间重叠
RECALL_K = 10                 # 向量召回数量
RERANK_TOP_N = 3              # Rerank 后保留数量
PERSIST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb_store")

# === 知识库名称 ===
KB_NAME = "personal_notes"

if __name__ == "__main__":
    print(f"LLM_MODEL   = {LLM_MODEL}")
    print(f"EMBED_MODEL = {EMBED_MODEL} ({EMBED_DIM}维)")
    print(f"RERANK_MODEL= {RERANK_MODEL}")
    print(f"RECALL_K    = {RECALL_K}, RERANK_TOP_N = {RERANK_TOP_N}")
    print(f"DOCS_DIR    = {DOCS_DIR}")
    print(f"PERSIST_DIR = {PERSIST_DIR}")

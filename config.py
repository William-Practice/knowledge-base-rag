"""
config.py — ① 配置层：所有模型/路径/参数集中管理

P0 改造（2026-11-06）
- 参数从"模块级常量"改为 RAGConfig 数据类：可由 JSON / 命令行注入，
  消融实验（chunk_size、rerank 开关等）不必再改源码重跑
- 保留模块级常量名（CHUNK_SIZE 等），旧脚本 `from config import *` 照常工作
- 新增 index_signature()：只挑"影响索引内容"的参数做指纹，
  改 temperature 之类不会误触发重建
"""

import os
import sys
import json
import argparse
from dataclasses import dataclass, replace as _dc_replace, asdict, fields


# 让 knowledge_base/ 能 import 上层项目模块（embedding_utils 等）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_HERE = os.path.dirname(os.path.abspath(__file__))


def load_env(path: str | None = None):
    """极简 .env 加载器（无第三方依赖）"""
    path = path or os.path.join(_HERE, ".env")
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

# === 智谱服务端 ===
LLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
LLM_API_KEY = os.getenv("ZHIPU_API_KEY", "")
RERANK_URL = os.getenv("ZHIPU_RERANK_URL", "https://open.bigmodel.cn/api/paas/v4/rerank")


@dataclass(frozen=True)
class RAGConfig:
    """一次实验的全部可调参数。不可变，用 .replace() 派生变体。"""

    # —— 切分（影响索引）——
    chunk_size: int = 500
    chunk_overlap: int = 50
    # 遇到 markdown 标题强制收尾，保证一块只属一个小节（见 loader._blocks 注释）
    heading_aware: bool = True
    # —— 检索（影响索引的只有 embed_*）——
    recall_k: int = 10
    rerank_top_n: int = 3
    embed_model: str = "embedding-2"
    embed_dim: int = 1024
    # —— 排序 / 生成 ——
    rerank_model: str = "rerank-pro"
    llm_model: str = "glm-4v-flash"
    temperature: float = 0.3
    # off / plain / protected / strict —— 实测 plain 是负收益，见 AGENTS.md §8.2
    rewrite_mode: str = "plain"
    # —— 路径 ——
    kb_name: str = "personal_notes"
    docs_dir: str = os.path.join(_HERE, "docs")
    persist_dir: str = os.path.join(_HERE, "kb_store")

    # ── 派生量 ──
    def store_path(self) -> str:
        return os.path.join(self.persist_dir, f"{self.kb_name}.json")

    def index_signature(self) -> dict:
        """决定'要不要重建索引'的参数子集。改 temperature 不该触发重建。"""
        return {
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "heading_aware": self.heading_aware,
            "embed_model": self.embed_model,
            "embed_dim": self.embed_dim,
        }

    # ── 构造 ──
    def replace(self, **kw) -> "RAGConfig":
        return _dc_replace(self, **kw)

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RAGConfig":
        d = {k: v for k, v in d.items() if not k.startswith("_")}  # 允许 _comment 之类注释键
        known = {f.name for f in fields(cls)}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"未知配置项: {sorted(unknown)}；可用项: {sorted(known)}")
        return cls(**d)

    @classmethod
    def from_json(cls, path: str) -> "RAGConfig":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def merged(self, override: "RAGConfig | dict | None") -> "RAGConfig":
        """把 override（dict 或另一个 RAGConfig）叠到自己上面"""
        if override is None:
            return self
        d = override if isinstance(override, dict) else override.as_dict()
        return self.replace(**d)


DEFAULT_CONFIG = RAGConfig()


# ── 向后兼容：旧代码 `from config import CHUNK_SIZE` 仍可用 ──
CHUNK_SIZE = DEFAULT_CONFIG.chunk_size
CHUNK_OVERLAP = DEFAULT_CONFIG.chunk_overlap
RECALL_K = DEFAULT_CONFIG.recall_k
RERANK_TOP_N = DEFAULT_CONFIG.rerank_top_n
EMBED_MODEL = DEFAULT_CONFIG.embed_model
EMBED_DIM = DEFAULT_CONFIG.embed_dim
RERANK_MODEL = DEFAULT_CONFIG.rerank_model
LLM_MODEL = DEFAULT_CONFIG.llm_model
DOCS_DIR = DEFAULT_CONFIG.docs_dir
PERSIST_DIR = DEFAULT_CONFIG.persist_dir
KB_NAME = DEFAULT_CONFIG.kb_name


# ── 命令行注入 ──
def add_config_args(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """给脚本挂上统一的 --config / 单项覆盖参数"""
    g = p.add_argument_group("配置")
    g.add_argument("--config", metavar="JSON", help="配置文件路径，覆盖默认值")
    g.add_argument("--chunk-size", type=int)
    g.add_argument("--chunk-overlap", type=int)
    g.add_argument("--heading-aware", dest="heading_aware", action="store_true", default=None)
    g.add_argument("--no-heading-aware", dest="heading_aware", action="store_false")
    g.add_argument("--recall-k", type=int)
    g.add_argument("--rerank-top-n", type=int)
    g.add_argument("--rerank-model")
    g.add_argument("--llm-model")
    g.add_argument("--temperature", type=float)
    g.add_argument("--kb-name")
    g.add_argument("--docs-dir")
    g.add_argument("--persist-dir")
    return p


def config_from_args(args, base: RAGConfig = DEFAULT_CONFIG) -> RAGConfig:
    """先读 --config 文件，再用命令行单项覆盖"""
    cfg = base
    if getattr(args, "config", None):
        cfg = cfg.merged(RAGConfig.from_json(args.config))
    pairs = {
        "chunk_size": "chunk_size", "chunk_overlap": "chunk_overlap",
        "heading_aware": "heading_aware",
        "recall_k": "recall_k", "rerank_top_n": "rerank_top_n",
        "rerank_model": "rerank_model", "llm_model": "llm_model",
        "temperature": "temperature", "kb_name": "kb_name",
        "docs_dir": "docs_dir", "persist_dir": "persist_dir",
    }
    kw = {k: getattr(args, k) for k in pairs if getattr(args, k, None) is not None}
    return cfg.replace(**kw)


def require_api_key():
    if not LLM_API_KEY:
        raise ValueError("缺少 ZHIPU_API_KEY，请在 .env 或环境变量中设置")
    return LLM_API_KEY


if __name__ == "__main__":
    cfg = DEFAULT_CONFIG
    print(f"chunk_size   = {cfg.chunk_size}  overlap = {cfg.chunk_overlap}")
    print(f"recall_k     = {cfg.recall_k}   rerank_top_n = {cfg.rerank_top_n}")
    print(f"embed_model  = {cfg.embed_model} ({cfg.embed_dim} 维)")
    print(f"rerank_model = {cfg.rerank_model}")
    print(f"llm_model    = {cfg.llm_model}")
    print(f"docs_dir     = {cfg.docs_dir}")
    print(f"store_path   = {cfg.store_path()}")
    print(f"API key      = {'已设置 (' + str(len(LLM_API_KEY)) + ' 字符)' if LLM_API_KEY else '❌ 未设置'}")
    print(f"index_sig    = {cfg.index_signature()}")

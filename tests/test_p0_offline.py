"""
tests/test_p0_offline.py — P0 改造的离线自检（不调 API、不花钱）

覆盖
  A. chunk 定位元信息：spans / offset / overlap_chars / char_len 自洽
  B. section 归属正确（markdown 标题）
  C. 语料指纹：稳定 + 对内容/文件名敏感
  D. 索引复用：指纹匹配 → 不重新向量化
  E. 语料变化 → 自动重建
  F. 切分参数变化 → 自动重建
  G. 生成参数变化（temperature）→ **不**重建
  H. 旧格式库（无 meta）→ 自动重建

运行
  python tests/test_p0_offline.py
"""

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile

os.environ.setdefault("ZHIPU_API_KEY", "stub-for-offline-test")

_KB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _KB)
sys.path.insert(0, os.path.dirname(_KB))   # embedding_utils.py 在项目根

import embedding_utils  # noqa: E402

CALLS = {"n": 0}


def _fake_embed(text: str) -> list[float]:
    """确定性假向量：只为验证流程，不代表语义"""
    CALLS["n"] += 1
    h = hashlib.sha256(text.encode("utf-8")).digest()
    return [b / 255.0 for b in h[:16]]


embedding_utils.embed = _fake_embed

import config  # noqa: E402
import loader  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"   {detail}" if detail and not cond else ""))


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


# ── A/B 切分元信息 ──────────────────────────────────────

MD = """# 一级标题

第一段内容，讲 Kafka 的 LEO 是什么，以及它和 HW 的关系。

## 二级标题

第二段内容，讲 HW 水位。这里还有第二行文字。

### 三级标题

第三段内容，只讲 ISR 的维护机制，与前面的内容无关。
"""


def test_chunk_meta():
    print("\n[A/B] 切分元信息与 section")
    parts = loader.chunk_text(MD, chunk_size=60, chunk_overlap=10)
    check("切分产生了 >1 块", len(parts) > 1, f"实际 {len(parts)} 块")

    keys = {"text", "spans", "offset", "overlap_chars", "char_len", "section"}
    check("每块都有完整字段", all(keys <= set(p) for p in parts))

    ok_len = all(p["char_len"] == len(p["text"]) for p in parts)
    check("char_len == len(text)", ok_len)

    ok_off = all(p["offset"] == [p["spans"][0][0], p["spans"][-1][1]] for p in parts)
    check("offset == [首 span 起, 末 span 止]", ok_off)

    ok_restore = True
    for p in parts:
        rebuilt = "".join(MD[s:e] for s, e in p["spans"])
        body = p["text"][p["overlap_chars"]:]
        if norm(rebuilt) != norm(body):
            ok_restore = False
            print(f"     不一致: {body[:40]!r} vs {rebuilt[:40]!r}")
    check("去掉 overlap 前缀后可由 spans 精确还原", ok_restore)

    ok_overlap = all(0 <= p["overlap_chars"] < p["char_len"] for p in parts)
    check("overlap_chars 落在 [0, char_len)", ok_overlap)

    # section：第一块在"一级标题"下，含 ISR 的块应归到"三级标题"
    check("首块 section = 一级标题", parts[0]["section"] == "一级标题",
          f"实际 {parts[0]['section']!r}")
    isr = [p for p in parts if "ISR" in p["text"]]
    check("ISR 块 section = 三级标题",
          bool(isr) and isr[-1]["section"] == "三级标题",
          f"实际 {[p['section'] for p in isr]}")

    # 块长约束（overlap 前缀会略微撑大，放宽 2 倍 overlap）
    # heading-aware 切分遇到"标题行单独成块"时会轻微超长以避免 10 字符碎块，
    # 因此这里允许少量超长，但不允许普遍超长
    over = [p["char_len"] for p in parts if p["char_len"] > 60 + 20]
    check("超长块只是少数（短缓冲合并的代价）",
          len(over) <= max(1, len(parts) // 3),
          f"超长 {len(over)}/{len(parts)} 块：{over}")


# ── C 指纹 ──────────────────────────────────────────────

def test_fingerprint(tmp):
    print("\n[C] 语料指纹")
    d = os.path.join(tmp, "fp")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "a.md"), "w", encoding="utf-8") as f:
        f.write("# A\n\n内容甲。\n")
    with open(os.path.join(d, "b.md"), "w", encoding="utf-8") as f:
        f.write("# B\n\n内容乙。\n")

    f1 = loader.corpus_fingerprint(loader.load_files(d))
    f2 = loader.corpus_fingerprint(loader.load_files(d))
    check("同一语料指纹稳定", f1 == f2, f"{f1} vs {f2}")

    with open(os.path.join(d, "a.md"), "a", encoding="utf-8") as f:
        f.write("多一个字\n")
    f3 = loader.corpus_fingerprint(loader.load_files(d))
    check("改内容 → 指纹变", f3 != f1, f"{f1} → {f3}")

    os.rename(os.path.join(d, "b.md"), os.path.join(d, "c.md"))
    f4 = loader.corpus_fingerprint(loader.load_files(d))
    check("改文件名 → 指纹变", f4 != f3, f"{f3} → {f4}")


# ── D-H 复用与重建 ──────────────────────────────────────

def test_reuse_and_rebuild(tmp):
    print("\n[D-H] 索引复用与自动重建")
    d = os.path.join(tmp, "docs")
    p = os.path.join(tmp, "store")
    os.makedirs(d, exist_ok=True)
    for i in range(3):
        with open(os.path.join(d, f"doc{i}.md"), "w", encoding="utf-8") as f:
            f.write(f"# 文档{i}\n\n" + f"这是第{i}篇的内容。" * 40 + "\n")

    cfg = config.DEFAULT_CONFIG.replace(docs_dir=d, persist_dir=p, kb_name="t", chunk_size=120)

    CALLS["n"] = 0
    kb1 = loader.build_index(cfg, verbose=False)
    n1 = CALLS["n"]
    check("首次建库调用了 embed", n1 == kb1["chunk_count"] and n1 > 0,
          f"chunk={kb1['chunk_count']} calls={n1}")
    check("库文件已落盘", os.path.exists(cfg.store_path()))
    check("meta 记录了 corpus_fp 与 index_signature",
          bool(kb1["meta"].get("corpus_fp")) and bool(kb1["meta"].get("index_signature")))

    # D 复用
    kb2 = loader.build_index(cfg, verbose=False)
    check("指纹一致 → 不再向量化", CALLS["n"] == n1, f"calls {n1} → {CALLS['n']}")
    check("复用返回同样块数", kb2["chunk_count"] == kb1["chunk_count"])

    # E 语料变化
    with open(os.path.join(d, "doc0.md"), "a", encoding="utf-8") as f:
        f.write("\n新增的一段完全不同的内容，足以改变指纹。\n")
    before = CALLS["n"]
    kb3 = loader.build_index(cfg, verbose=False)
    check("语料变化 → 触发重建", CALLS["n"] > before, f"calls {before} → {CALLS['n']}")
    check("重建后指纹已更新", kb3["meta"]["corpus_fp"] != kb1["meta"]["corpus_fp"])

    # F 切分参数变化
    cfg_big = cfg.replace(chunk_size=60)
    before = CALLS["n"]
    kb4 = loader.build_index(cfg_big, verbose=False)
    check("chunk_size 变化 → 触发重建", CALLS["n"] > before, f"calls {before} → {CALLS['n']}")
    check("更小的 chunk 产生更多块", kb4["chunk_count"] > kb3["chunk_count"],
          f"{kb3['chunk_count']} → {kb4['chunk_count']}")

    # G 生成参数变化 → 不重建
    cfg_temp = cfg_big.replace(temperature=0.9, recall_k=5)
    before = CALLS["n"]
    loader.build_index(cfg_temp, verbose=False)
    check("temperature/recall_k 变化 → 不重建", CALLS["n"] == before,
          f"calls {before} → {CALLS['n']}")

    # H 旧格式库（无 meta）
    with open(cfg_temp.store_path(), "w", encoding="utf-8") as f:
        json.dump({"chunks": [], "doc_count": 0, "chunk_count": 0}, f)
    before = CALLS["n"]
    kb6 = loader.build_index(cfg_temp, verbose=False)
    check("旧格式库（无 meta）→ 触发重建", CALLS["n"] > before and kb6["chunk_count"] > 0,
          f"calls {before} → {CALLS['n']}")

    # dry-run 不该调 API
    before = CALLS["n"]
    kb7 = loader.build_index(cfg_temp, dry_run=True, verbose=False)
    check("dry-run 不调用 embed", CALLS["n"] == before, f"calls {before} → {CALLS['n']}")
    check("dry-run 仍产出切分结果", kb7["chunk_count"] > 0)


def main():
    tmp = tempfile.mkdtemp(prefix="kb_p0_")
    try:
        test_chunk_meta()
        test_fingerprint(tmp)
        test_reuse_and_rebuild(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "═" * 54)
    print(f"通过 {len(PASS)} / {len(PASS)+len(FAIL)}")
    if FAIL:
        print("失败：")
        for f in FAIL:
            print(f"  · {f}")
        return 1
    print("✅ 全部通过（未调用任何 API）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
loader.py — ② 数据层：加载 → 切分（带定位元信息）→ 向量化 → 持久化建库

P0 改造（2026-11-06）
1. chunk 带定位元信息：source / section / spans / offset / overlap_chars / char_len
   —— 评测标注、错误分析、命中后扩展上下文都依赖它；缺了它，语料一换 gold 标注全废
2. 建库时记录两份指纹：
     corpus_fp       语料内容 sha256（改一个字就变）
     index_signature chunk_size / overlap / embed_model / embed_dim
   加载时比对，任一不符自动重建 —— 根治"换了语料还在读旧库"
3. 参数全部由 RAGConfig 注入，不再读模块常量（消融实验前置）

离线可用：`python loader.py --dry-run` 只切分+统计，不调 API。
"""

import glob
import hashlib
import json
import os
import re
import time

from config import DEFAULT_CONFIG, RAGConfig, add_config_args, config_from_args

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_BLANK = re.compile(r"\n[ \t]*\n")
_SENT_END = "。！？；\n.!?;"

STORE_FORMAT = 2


# ── 加载 ────────────────────────────────────────────────

def list_doc_paths(docs_dir: str) -> list[str]:
    """递归收集 md/txt（支持 kb_corpus/kafka/*.md 这类子目录结构）"""
    paths = []
    for ext in ("*.md", "*.txt"):
        paths += glob.glob(os.path.join(docs_dir, "**", ext), recursive=True)
    return sorted(paths)


def load_files(docs_dir: str = DEFAULT_CONFIG.docs_dir) -> list[dict]:
    """读取 docs/ 下 md/txt → [{source, path, text, sha256}]"""
    docs = []
    for f in list_doc_paths(docs_dir):
        try:
            with open(f, encoding="utf-8") as fh:
                text = fh.read()
        except Exception as e:
            print(f"  ⚠ 跳过 {os.path.basename(f)}: {e}")
            continue
        if not text.strip():
            continue
        docs.append({
            # 相对 docs_dir 的路径，子目录保留（kafka/xxx.md）；平铺语料仍是纯文件名
            "source": os.path.relpath(f, docs_dir).replace(os.sep, "/"),
            "path": f,
            "text": text,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        })
    return docs


def corpus_fingerprint(docs: list[dict]) -> str:
    """语料指纹：文件名 + 内容哈希，与切分参数无关"""
    h = hashlib.sha256()
    for d in sorted(docs, key=lambda x: x["source"]):
        h.update(d["source"].encode("utf-8"))
        h.update(b"\x00")
        h.update(d["sha256"].encode("ascii"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


# ── 切分 ────────────────────────────────────────────────

def _blocks(text: str) -> list[tuple[int, int]]:
    """按空行切段，返回去除首尾空白后的字符区间"""
    spans, pos = [], 0
    for m in _BLANK.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))

    out = []
    for s, e in spans:
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if e > s:
            out.append((s, e))
    return out


def _split_long(text: str, s: int, e: int, size: int) -> list[tuple[int, int]]:
    """单段超过 size 时硬切，优先切在句末标点上"""
    out, cur = [], s
    while e - cur > size:
        hard = cur + size
        cut = hard
        for i in range(hard, cur + size // 2, -1):
            if text[i - 1] in _SENT_END:
                cut = i
                break
        out.append((cur, cut))
        cur = cut
        while cur < e and text[cur].isspace():
            cur += 1
    if e > cur:
        out.append((cur, e))
    return out


def _overlap_tail(buf: str, overlap: int) -> str:
    """取上一块尾部作重叠前缀；尽量从整句开头，避免 chunk 以半句话起头"""
    if overlap <= 0 or not buf:
        return ""
    tail = buf[-overlap:]
    window = buf[-(overlap + 40):] if len(buf) > overlap + 40 else buf
    idx = max(window.rfind(ch) for ch in _SENT_END)
    if idx != -1:
        cand = window[idx + 1:].lstrip()
        if overlap // 2 <= len(cand) <= overlap * 2:
            return cand
    return tail.lstrip()


def chunk_text(text: str,
               chunk_size: int = DEFAULT_CONFIG.chunk_size,
               chunk_overlap: int = DEFAULT_CONFIG.chunk_overlap) -> list[dict]:
    """
    切分并保留定位信息。

    每块返回：
      text           块文本（开头可能含上一块的 overlap 前缀）
      spans          [[s,e], ...] 该块**主内容**在原文中的片段区间（可精确还原）
      offset         [s, e] 主内容整体跨度
      overlap_chars  text 开头有多少字符是重叠前缀（不属于主内容）
      char_len       len(text)
      section        块起始处所在的最近一级 markdown 标题
    """
    chunks: list[dict] = []
    section = ""
    buf = ""
    spans: list[tuple[int, int]] = []
    carried = 0
    buf_section = ""

    def emit():
        nonlocal buf, spans, carried, buf_section
        body = buf.strip()
        if not body or not spans:
            buf, spans, carried = "", [], 0
            return
        chunks.append({
            "text": body,
            "spans": [[s, e] for s, e in spans],
            "offset": [spans[0][0], spans[-1][1]],
            "overlap_chars": min(carried, len(body)),
            "char_len": len(body),
            "section": buf_section,
        })
        buf, spans, carried = "", [], 0

    for s, e in _blocks(text):
        seg = text[s:e]
        m = _HEADING.match(seg)
        if m:
            section = m.group(2).strip()

        pieces = [(s, e)] if (e - s) <= chunk_size else _split_long(text, s, e, chunk_size)
        for ps, pe in pieces:
            piece = text[ps:pe]
            if not buf:
                buf, spans, carried, buf_section = piece, [(ps, pe)], 0, section
            elif len(buf) + 1 + len(piece) <= chunk_size:
                buf = buf + "\n" + piece
                spans.append((ps, pe))
            else:
                tail = _overlap_tail(buf, chunk_overlap)   # 必须先取，emit() 会清空 buf
                emit()
                buf = piece
                spans, buf_section = [(ps, pe)], section
                carried = 0
                if tail:
                    buf = tail + "\n" + piece
                    carried = len(tail) + 1

    emit()
    return chunks


# ── 建库 ────────────────────────────────────────────────

def _rebuild_reason(old_meta: dict, fp: str, sig: dict) -> str:
    if not old_meta:
        return "旧库无 meta（格式升级）"
    if old_meta.get("format") != STORE_FORMAT:
        return f"库格式 {old_meta.get('format')} → {STORE_FORMAT}"
    if old_meta.get("corpus_fp") != fp:
        return f"语料变化 {old_meta.get('corpus_fp')} → {fp}"
    old_sig = old_meta.get("index_signature") or {}
    diff = {k: (old_sig.get(k), v) for k, v in sig.items() if old_sig.get(k) != v}
    if diff:
        return "切分/嵌入参数变化 " + ", ".join(f"{k}: {a}→{b}" for k, (a, b) in diff.items())
    return "未知"


def build_index(cfg: RAGConfig = DEFAULT_CONFIG, force: bool = False,
                dry_run: bool = False, verbose: bool = True) -> dict:
    """
    加载 → 切分 → 向量化 → 持久化。已存在且指纹匹配则直接复用。

    :param dry_run: 只切分统计，不调 API、不写盘（离线可用）
    """
    t0 = time.perf_counter()
    docs = load_files(cfg.docs_dir)
    if not docs:
        if verbose:
            print(f"⚠ {cfg.docs_dir} 下没有可加载的文档")
        return {"chunks": [], "doc_count": 0, "chunk_count": 0, "meta": {}}

    fp = corpus_fingerprint(docs)
    sig = cfg.index_signature()
    store = cfg.store_path()

    # ── 复用判定 ──
    if not force and not dry_run and os.path.exists(store):
        old = None
        try:
            with open(store, encoding="utf-8") as f:
                old = json.load(f)
        except Exception as e:
            if verbose:
                print(f"⚠ 旧库读取失败（{e}），重建")
        if old is not None:
            meta = old.get("meta") or {}
            if (meta.get("format") == STORE_FORMAT
                    and meta.get("corpus_fp") == fp
                    and meta.get("index_signature") == sig):
                if verbose:
                    print(f"✅ 索引有效，直接加载 {store}")
                    print(f"   {old.get('chunk_count')} 块 / {old.get('doc_count')} 文件 "
                          f"/ 建于 {meta.get('built_at')}")
                return old
            if verbose:
                print(f"♻ 索引失效，重建：{_rebuild_reason(meta, fp, sig)}")

    # ── 切分 ──
    chunks: list[dict] = []
    for doc in docs:
        for part in chunk_text(doc["text"], cfg.chunk_size, cfg.chunk_overlap):
            part["chunk_id"] = len(chunks) + 1
            part["source"] = doc["source"]
            chunks.append(part)

    total_chars = sum(len(d["text"]) for d in docs)
    if verbose:
        print(f"切分完成：{len(docs)} 个文件 / {total_chars:,} 字符 → {len(chunks)} 块"
              f"（chunk_size={cfg.chunk_size}, overlap={cfg.chunk_overlap}）")

    if dry_run:
        secs = time.perf_counter() - t0
        lens = sorted(c["char_len"] for c in chunks)
        if verbose and chunks:
            print(f"  块长 min/中位/max = {lens[0]}/{lens[len(lens)//2]}/{lens[-1]}")
            print(f"  切分耗时 {secs:.2f}s（dry-run 未向量化）")
        return {"chunks": chunks, "doc_count": len(docs),
                "chunk_count": len(chunks),
                "meta": {"corpus_fp": fp, "index_signature": sig, "dry_run": True}}

    # ── 向量化（串行；P1 改真批量）──
    from embedding_utils import embed  # 延迟导入：dry-run 不需要 API
    t_embed = time.perf_counter()
    for i, c in enumerate(chunks):
        c["vec"] = embed(c["text"])
        if verbose and ((i + 1) % 10 == 0 or i == len(chunks) - 1):
            print(f"  向量化 {i+1}/{len(chunks)}  ({time.perf_counter()-t_embed:.1f}s)")
    embed_secs = time.perf_counter() - t_embed

    meta = {
        "format": STORE_FORMAT,
        "corpus_fp": fp,
        "index_signature": sig,
        "config": cfg.as_dict(),
        "doc_count": len(docs),
        "chunk_count": len(chunks),
        "total_chars": total_chars,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "build_seconds": round(time.perf_counter() - t0, 2),
        "embed_seconds": round(embed_secs, 2),
        "sources": [{"source": d["source"], "sha256": d["sha256"],
                     "chars": len(d["text"])} for d in docs],
    }
    data = {"chunks": chunks, "doc_count": len(docs),
            "chunk_count": len(chunks), "meta": meta}

    os.makedirs(cfg.persist_dir, exist_ok=True)
    with open(store, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    if verbose:
        print(f"✅ 建库完成 {store}")
        print(f"   向量化 {embed_secs:.1f}s / 总计 {meta['build_seconds']}s / "
              f"{os.path.getsize(store)/1e6:.1f} MB")
    return data


def main():
    import argparse
    p = argparse.ArgumentParser(description="建库（默认复用有效索引）")
    add_config_args(p)
    p.add_argument("--force", action="store_true", help="强制重建")
    p.add_argument("--dry-run", action="store_true", help="只切分统计，不调 API")
    args = p.parse_args()
    build_index(config_from_args(args), force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

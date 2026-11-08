"""
tests/test_p1_retriever.py — P1 ①③ 的离线自检（mock 掉 embed 与 rerank HTTP）

覆盖
  A. 重复文本 + rerank 返回 index   → 两个不同的 chunk 都要出现，不能互相覆盖
  B. 重复文本 + rerank 返回 document → 按出现顺序逐个消费
  C. rerank 返回未知 document       → 抛异常（不允许 chunks[0] 兜底）
  D. rerank 返回越界 index          → 抛异常
  E. recall_k <= rerank_top_n       → RuntimeWarning + rerank_applied=False + 不发请求
  F. 正常路径                        → rerank_applied=True，顺序 = API 返回顺序

运行
  python tests/test_p1_retriever.py
"""

import json
import os
import sys
import types
import warnings

os.environ.setdefault("ZHIPU_API_KEY", "stub-for-offline-test")

_KB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _KB)
sys.path.insert(0, os.path.dirname(_KB))

import retriever  # noqa: E402
from config import DEFAULT_CONFIG  # noqa: E402

PASS, FAIL = [], []
URLOPEN_CALLS = {"n": 0}


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"   {detail}" if detail and not cond else ""))


class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _UR:
    """假 urllib.request：同时提供 Request 与 urlopen"""

    def __init__(self, payload):
        self.payload = payload

    def Request(self, url, data=None, headers=None):
        return types.SimpleNamespace(url=url, data=data, headers=headers or {})

    def urlopen(self, req, timeout=None):
        URLOPEN_CALLS["n"] += 1
        self.last = req
        return _Resp(self.payload)


def install(payload):
    """把 retriever 里的 urllib 换成本地假实现（不影响全局 urllib）"""
    retriever.urllib = types.SimpleNamespace(request=_UR(payload))


# 让所有 chunk 向量相同 → 召回分数并列，稳定排序下按原始下标排序，结果可预测
retriever.embed = lambda q: [1.0, 0.0]


def make_kb(texts):
    return {"chunks": [
        {"chunk_id": i + 1, "text": t, "vec": [1.0, 0.0], "source": "s.md",
         "section": "§", "offset": [0, len(t)], "char_len": len(t)}
        for i, t in enumerate(texts)
    ]}


def test_duplicate_text_with_index():
    print("\n[A] 重复文本 + rerank 返回 index")
    kb = make_kb(["A 段内容", "B 段内容", "A 段内容"])   # 下标 0 与 2 文本相同
    install({"results": [
        {"index": 2, "relevance_score": 0.91},
        {"index": 0, "relevance_score": 0.44},
    ]})
    out = retriever._rerank("q", [dict(c) for c in kb["chunks"]], top_n=2, cfg=DEFAULT_CONFIG)
    ids = [c["chunk_id"] for c in out]
    check("两个不同 chunk 都被返回", ids == [3, 1], f"实际 {ids}")
    check("分数各归各位", [c["rerank_score"] for c in out] == [0.91, 0.44],
          f"实际 {[c['rerank_score'] for c in out]}")
    check("rerank_applied = True", all(c["rerank_applied"] for c in out))


def test_duplicate_text_with_document():
    print("\n[B] 重复文本 + rerank 返回 document 文本（无 index）")
    kb = make_kb(["同名片段", "别的片段", "同名片段"])
    install({"results": [
        {"document": "同名片段", "relevance_score": 0.88},
        {"document": "同名片段", "relevance_score": 0.77},
    ]})
    out = retriever._rerank("q", [dict(c) for c in kb["chunks"]], top_n=2, cfg=DEFAULT_CONFIG)
    ids = [c["chunk_id"] for c in out]
    check("按出现顺序映射到 1 和 3", ids == [1, 3], f"实际 {ids}")


def test_unknown_document():
    print("\n[C] rerank 返回未知 document → 必须抛异常（不能 chunks[0] 兜底）")
    kb = make_kb(["甲", "乙", "丙"])
    install({"results": [{"document": "根本没这段", "relevance_score": 0.9}]})
    try:
        retriever._rerank("q", [dict(c) for c in kb["chunks"]], top_n=2, cfg=DEFAULT_CONFIG)
        check("抛出 RuntimeError", False, "没有抛异常")
    except RuntimeError as e:
        check("抛出 RuntimeError", True)
        check("错误信息含文档前缀", "根本没这段"[:10] in str(e) or "找不到" in str(e), str(e)[:60])


def test_index_out_of_range():
    print("\n[D] rerank 返回越界 index → 抛异常")
    kb = make_kb(["甲", "乙", "丙"])
    install({"results": [{"index": 99, "relevance_score": 0.9}]})
    try:
        retriever._rerank("q", [dict(c) for c in kb["chunks"]], top_n=2, cfg=DEFAULT_CONFIG)
        check("抛出 RuntimeError", False, "没有抛异常")
    except RuntimeError as e:
        check("抛出 RuntimeError", True, str(e)[:40])


def test_short_circuit():
    print("\n[E] recall_k <= rerank_top_n → 短路必须可见")
    kb = make_kb(["甲", "乙", "丙"])
    install({"results": [{"index": 0, "relevance_score": 0.9}]})
    before = URLOPEN_CALLS["n"]
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = retriever.search("q", kb, recall_k=3, rerank_top_n=3, cfg=DEFAULT_CONFIG)
    check("发出 RuntimeWarning", any(issubclass(x.category, RuntimeWarning) for x in w),
          f"捕获 {[x.category.__name__ for x in w]}")
    check("没有发 rerank 请求", URLOPEN_CALLS["n"] == before,
          f"调用数 {before} → {URLOPEN_CALLS['n']}")
    check("rerank_applied 全为 False（不冒充已精排）",
          out and all(c["rerank_applied"] is False for c in out))


def test_normal_path():
    print("\n[F] 正常路径：结果顺序 = API 返回顺序")
    kb = make_kb(["一", "二", "三", "四", "五"])
    install({"results": [
        {"index": 4, "relevance_score": 0.95},
        {"index": 1, "relevance_score": 0.51},
    ]})
    out = retriever.search("q", kb, recall_k=5, rerank_top_n=2, cfg=DEFAULT_CONFIG)
    ids = [c["chunk_id"] for c in out]
    check("取到 5 号和 2 号", ids == [5, 2], f"实际 {ids}")
    check("rerank_applied 全为 True", all(c["rerank_applied"] for c in out))
    check("保留了召回分与召回名次",
          all("score" in c and "recall_rank" in c for c in out))


def main():
    test_duplicate_text_with_index()
    test_duplicate_text_with_document()
    test_unknown_document()
    test_index_out_of_range()
    test_short_circuit()
    test_normal_path()

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

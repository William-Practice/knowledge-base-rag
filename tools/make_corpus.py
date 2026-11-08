"""
tools/make_corpus.py — 从 ~/notes 生成一份**冻结**的语料快照

为什么要冻结
    评测必须可复现。如果语料是软链，notes 一改，昨天跑出的 recall 就再也复现不了。
    所以这里是拷贝，不是软链；每个文件的 sha256 记进 manifest。

为什么 manifest 可以进仓库
    manifest 只有路径 + 哈希 + 字符数，没有内容。
    提交它 = 公开"我用的是哪 31 篇、各多少字"，但不泄露一个字。
    语料本体（kb_corpus/）始终在 .gitignore 里。

用法
    python tools/make_corpus.py                       # 默认档 1
    python tools/make_corpus.py --dirs kafka flink --out kb_corpus
"""

import argparse
import hashlib
import json
import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_KB = os.path.dirname(_HERE)

DEFAULT_SRC = os.path.expanduser("~/notes")
TIER1 = ["kafka", "flink", "llm-dev", "hadoop", "spark", "zookeeper"]
# 明确排除：含个人信息 / 机构名的目录，见 AGENTS.md §5 红线①
FORBIDDEN = {"other", "project"}


def collect(src_root: str, dirs: list[str]) -> list[dict]:
    out = []
    for d in dirs:
        if d in FORBIDDEN:
            raise SystemExit(f"❌ {d}/ 在红线禁入名单里（见 AGENTS.md §5）")
        base = os.path.join(src_root, d)
        if not os.path.isdir(base):
            print(f"  ⚠ 跳过不存在的目录 {base}")
            continue
        for name in sorted(os.listdir(base)):
            if not name.endswith((".md", ".txt")):
                continue
            path = os.path.join(base, name)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as f:
                text = f.read()
            out.append({
                "dir": d,
                "name": name,
                "src": path,
                "text": text,
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "chars": len(text),
            })
    return out


def main():
    ap = argparse.ArgumentParser(description="生成冻结语料快照")
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--dirs", nargs="+", default=TIER1)
    ap.add_argument("--out", default=os.path.join(_KB, "kb_corpus"))
    ap.add_argument("--manifest", default=os.path.join(_KB, "kb_corpus.manifest.json"))
    ap.add_argument("--force", action="store_true", help="目标目录已存在时清空重建")
    args = ap.parse_args()

    files = collect(args.src, args.dirs)
    if not files:
        raise SystemExit("❌ 没有收集到任何文件")

    if os.path.isdir(args.out):
        if not args.force:
            raise SystemExit(f"❌ {args.out} 已存在；确认要重建请加 --force")
        shutil.rmtree(args.out)

    for f in files:
        dst_dir = os.path.join(args.out, f["dir"])
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copy2(f["src"], os.path.join(dst_dir, f["name"]))

    per_dir: dict[str, dict] = {}
    for f in files:
        d = per_dir.setdefault(f["dir"], {"files": 0, "chars": 0})
        d["files"] += 1
        d["chars"] += f["chars"]

    manifest = {
        "frozen_at": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        "source_root": args.src.replace(os.path.expanduser("~"), "~"),
        "dirs": args.dirs,
        "excluded": sorted(FORBIDDEN),
        "totals": {"files": len(files), "chars": sum(f["chars"] for f in files)},
        "per_dir": per_dir,
        "files": [{"path": f"{f['dir']}/{f['name']}", "sha256": f["sha256"],
                   "chars": f["chars"]} for f in files],
    }
    with open(args.manifest, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    print(f"✅ 快照 {args.out}")
    print(f"   {len(files)} 文件 / {manifest['totals']['chars']:,} 字符")
    for d, v in per_dir.items():
        print(f"     {d:<12} {v['files']:>3} 篇  {v['chars']:>7,} 字符")
    print(f"   manifest → {args.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

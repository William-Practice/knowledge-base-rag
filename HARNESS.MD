# HARNESS.MD — 本项目通用 harness 入口（不自动读 AGENTS.md 的平台）

> **公开事实源：本目录的 `README.md`**。本文件是入口副本，给 DeepSeek harness、Cursor、
> 自研 harness 等"给一段提示词就开始干活"的平台用。
> （本地工作副本可能另有 `AGENTS.md`，不随仓库分发；若存在则一并读。）
>
> **用法**：首次提示的第一行写 ——
> `先读 ./HARNESS.MD 和 ./README.md，不要重新调查现状。`

---

## 0. 一句话

**共享上下文靠文件，不靠粘贴。** 把另一个 agent 的输出整段转述过来，每过一手掉一层，
两边都烧额度。正确做法是给**文件路径**，让它自己读。

---

## 1. 这个项目是什么

**31 篇个人工程笔记上的 RAG 检索系统，带可复现的评测与消融。**

```
语料   31 篇 / 167,966 字符（kb_corpus/，冻结快照 + manifest，不入库）
索引   531 块（chunk_size=500 / overlap=50 / heading-aware）
模型   智谱 embedding-2（1024 维）/ rerank-pro / glm-4v-flash，纯 HTTP，无 LangChain / Chroma
评测   60 题（20 术语 / 20 跨文档 / 20 口语化），gold 由「章节 + 锚点」机械解析
当前   rewrite off + rerank on → hit@10 0.833 / hit@3 0.667 / MRR 0.589
```

---

## 2. 红线（**本目录是 PUBLIC 仓库**，违反即不可撤回）

```
R1  语料一律不进 git。kb_corpus/ 已在 .gitignore
R2  不得出现个人信息：本机绝对路径（如 ~/...）、API Key、身份证、手机号、其他项目内容
R3  不换框架：不引入 LangChain / Chroma / 向量数据库
R4  数字只能来自 eval/results/*.csv 与 bench/*.json，不得手写
R5  只报配置之间的相对增益，不宣称绝对召回水平与泛化性
R6  一个仓库同一时间只给一个 agent；动手前先 git status
R7  验收要原始输出，不接受"已完成"
R8  失败就是失败，不要美化
```

---

## 3. 交接模板（复制改填）

```
在本目录里 <一句话目标>。

先读这些文件了解背景，**不要重新调查**：
  ./HARNESS.MD
  ./README.md
  eval/results/summary.csv

关键约束：
  · 本目录是 PUBLIC 仓库，语料与个人信息不得入库
  · 不引入 LangChain / Chroma，直接用 REST
  · 改检索逻辑后必须重跑 60 题，并与 eval/results/summary.csv 对照

范围：只做 <...>，不要 <越界动作，例如重建索引 / 改评测集 / 动 docs/>。

验收（把这三条命令的**原始输出**贴回来，不要复述）：
  python tests/test_p0_offline.py | tail -2                        # 期望 25/25
  python eval/run_eval.py --config configs/v2_tier1.json --rewrite-mode off --tag <tag>
  git status --porcelain | grep -c '\.md$'                         # 期望 0
```

三层缺任何一层的症状：

```
缺指路      重新调查一遍，结论与 README 矛盾，白烧额度
缺不做清单  自作主张（换框架、重建索引、改评测集）
缺验收      宣布"已完成"，实际没验证 —— 自述 ≠ 事实
```

---

## 4. 常用命令

```bash
python loader.py --config configs/v2_tier1.json               # 建库 / 复用
python loader.py --config configs/v2_tier1.json --dry-run     # 只切分，不调 API
python eval/resolve_gold.py --write                           # 改题或换切分后重解析 gold
python eval/run_eval.py --config configs/v2_tier1.json --rewrite-mode off --tag baseline
python bench/probe_baseline.py --config configs/v2_tier1.json --queries 5
```

---

## 5. 已知短板（别当成就）

```
跨文档题全目标覆盖仅 0.235   需要查询分解 / 多轮检索
31 篇语料不足以断言泛化性    结论只限配置间相对差异
生成层未接入评测            占全链路 67%，无覆盖
```

---

## 6. 变更日志

```
2026-11-09  建立。与 AGENT.md、CLAUDE.MD 同批，均为 AGENTS.md 的入口副本。
```

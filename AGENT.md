# AGENT.md — 本项目的 agent 入口（单数拼写）

> **公开事实源：本目录的 `README.md`**（定位 / 结果表 / 复现步骤 / 已知限制）。
> 本文件是它的入口副本，只保留"不读全文也不能违反"的部分；冲突时以 `README.md` 与
> `eval/results/summary.csv` 为准。
> （本地工作副本可能另有一份 `AGENTS.md` 任务书，**不随仓库分发**；若存在，以它为准。）
>
> 为什么有这份：部分工具只认单数 `AGENT.md`，而 Hermes / Codex / Claude Code 认 `AGENTS.md`。
> 能读 `AGENTS.md` 的平台不必读本文件。

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
R1  语料一律不进 git。kb_corpus/ 已在 .gitignore；任何 .md 语料出现在 git status 里都算事故
R2  不得出现个人信息：本机绝对路径（如 ~/...）、API Key、身份证、手机号、其他项目的内容
R3  不换框架：不引入 LangChain / Chroma / 向量数据库。直接用 REST 是这个项目的设计选择
R4  数字只能来自 eval/results/*.csv 与 bench/*.json，不得手写、不得四舍五入后当成新结果
R5  报告纪律：只报**配置之间的相对增益**，不宣称绝对召回水平与泛化性
R6  一个仓库同一时间只给一个 agent；动手前先 git status
R7  验收要原始输出（命令 + stdout），不接受"已完成""已修复"
R8  失败就是失败，不要为了好看而重述或省略异常
```

---

## 3. 常用命令

```bash
# 建库（已存在且指纹匹配则直接复用；语料或切分参数变了会自动重建）
python loader.py --config configs/v2_tier1.json

# 只切分不调 API（离线，零成本）
python loader.py --config configs/v2_tier1.json --dry-run

# 评测：一组配置跑满 60 题
python eval/run_eval.py --config configs/v2_tier1.json --rewrite-mode off --tag baseline
python eval/run_eval.py --config configs/v2_tier1.json --rewrite-mode off --no-rerank --tag no_rerank

# 离线断言（mock 模型调用，不需要额度）
python tests/test_p0_offline.py      # 25 项
python tests/test_p1_retriever.py    # 13 项

# 分段耗时基线
python bench/probe_baseline.py --config configs/v2_tier1.json --queries 5
```

**gold 解析**（改了题或换了切分后必须重跑）：

```bash
python eval/resolve_gold.py            # 只报告
python eval/resolve_gold.py --write    # 写回 eval_set_v2.json
```

---

## 4. 验收（贴原始输出，不要复述）

```bash
python tests/test_p0_offline.py | tail -2      # 期望：通过 25 / 25
python tests/test_p1_retriever.py | tail -2    # 期望：通过 13 / 13
git status --porcelain | grep -c '\.md$'       # 期望：0（没有语料混入）
```

---

## 5. 已知短板（别当成就）

```
跨文档题全目标覆盖仅 0.235   一个 chunk 装不下两处事实 → 需要查询分解 / 多轮检索
31 篇语料不足以断言泛化性    结论只限配置间相对差异
生成层未接入评测            占全链路 67%，目前无覆盖
```

---

## 6. 变更日志

```
2026-11-09  建立。与 CLAUDE.MD、HARNESS.MD 同批，均为 AGENTS.md 的入口副本。
```

# 个人笔记 RAG 检索系统

> 31 篇工程笔记 / 167,966 字符 / 457 块，5 层架构，纯 HTTP 调模型，**带可复现的检索评测与消融**。

一句话定位：这不是一个"我搭了个 RAG"的 demo，而是一个**能证伪自己的检索实验平台** ——
下面每条结论都有对应的跑批脚本、落盘结果和重跑次数。

---

## 先给结论（都是本项目实测，不是常识）

| 结论 | 数字 | 依据 |
|---|---|---|
| **Query 改写是负收益**，且引入非确定性 | hit@10 `0.80~0.85 → 0.95`，MRR `0.675 → 0.742`，还快 0.6 s | `eval/results/summary.csv` |
| Rerank 是真收益 | MRR `+0.225`（0.450 → 0.675），代价 `+0.39 s` | 同上 |
| **向量检索层不值得优化** | 457 块本地余弦扫描 28 ms = 全链路 **0.6%** | `bench/probe_baseline.py` |
| 生成是唯一的耗时大头 | 占全链路 **65.5%**，吞吐 128 字符/秒 | 同上 |

两条当时很反直觉、后来被数据推着改主意的：

- 一开始判断"`glm-4v-flash` 是视觉模型、拿来做文本生成是选型错误，换 `glm-4-flash` 会更快"。
  实测 `glm-4-flash` 只有 **35 字符/秒**，是 `glm-4v-flash`（128 字符/秒）的 27% —— **选它是对的，但原代码没写清楚理由**。
- 一开始打算给向量检索加 `npy` 存盘和 numpy 矩阵化。测完发现这一层占 0.1%，
  做完最多省 4 毫秒 —— **取消**。

> 优化的第一件事是确认瓶颈在哪，不是先把热门技术堆上去。

---

## 为什么改写是负收益（逐题查证过机制）

| 问题 | 改写后 | 后果 |
|---|---|---|
| `mapred-site.xml 里怎么让 MapReduce 跑在 YARN 上` | `mapreduce-site.xml ...` | **文件名被改错**，名次 9 → 未命中 |
| `配 SSH 免密登录，具体怎么操作` | `如何实现免密登录` | 丢掉 `SSH` 这个实体 |
| `偏移量重置到最早或者最新` | `重置方法是什么` | 丢掉具体目标 |
| `ISR 是什么` | `ISR（In-Sync Replicas）是什么` | 唯一变好的类型：展开缩写 |

即：**改写会动专有名词和标识符，而这些恰恰是技术笔记检索最有效的信号。**

为此实现了"关键词保护改写"（`generator.rewrite_query(mode=protected|strict)`）：
把问题里所有 ASCII token 当受保护词，改写后丢失就补回 / 整体退回原问题。

结果：**只修好一半。**

- ✅ `mapred-site.xml` 保住了，该题恢复命中（指标可证）
- ❌ 中文细节丢失（`最早或最新` → `重置方法`）token 保护覆盖不到
- ❌ 有一题保住 `SSH` 后名次仍从 9 掉到 11 —— 属于边缘排名抖动，不是实体丢失

结论：**默认关掉改写**。保护版保留为可选模式，边界写在代码注释里。

---

## 语料

| 目录 | 篇数 | 字符 |
|---|---|---|
| kafka | 12 | 56,231 |
| flink | 6 | 35,727 |
| hadoop | 4 | 28,518 |
| llm-dev | 4 | 28,217 |
| spark | 4 | 16,055 |
| zookeeper | 1 | 3,218 |
| **合计** | **31** | **167,966** |

切成 **457 块**（`chunk_size=500` / `overlap=50`），块长 65 / 433 / 550（min / 中位 / max），
`section` 元信息覆盖 99.3%。

语料是个人笔记，**不随仓库分发**。仓库里只有 `kb_corpus.manifest.json` ——
每篇的路径、sha256、字符数，没有内容。这样对外可以说清"用了什么"，但不泄露一个字。

想复现的话：

```bash
# 用你自己的 markdown 笔记（保持 <目录>/<子目录>/*.md 结构）
python tools/make_corpus.py --src ~/notes --dirs kafka flink hadoop spark
# 或者先用仓库自带的 docs/ 5 篇跑通链路
python loader.py --docs-dir docs --kb-name smoke
```

---

## 架构

```
① config.py     参数集中管理（frozen dataclass），支持 --config JSON 与 CLI 单项覆盖
② loader.py     加载 → 切分（带 source/section/spans/offset）→ 向量化 → 持久化
③ retriever.py  向量召回 TopK → rerank 精排 TopN
④ generator.py  Query 改写（4 种模式）+ Prompt 拼接 + 生成
⑤ api.py        FastAPI：/ask + /health
```

模型全部走智谱开放平台，纯 `urllib` + `json`，**不依赖 LangChain / Chroma**：
`embedding-2`（1024 维）/ `rerank-pro` / `glm-4v-flash`。

不用框架是刻意的 —— 能讲清 embedding 和 rerank 的原始协议，比会调包有用。

---

## 快速开始

```bash
pip install fastapi uvicorn
export ZHIPU_API_KEY='你的 key'

# 1. 建库（需要 kb_corpus/，见上节；已建好则复用）
python loader.py --config configs/v2_tier1.json

# 2. 评测：20 题，输出 hit@10 / hit@3 / MRR / 分段延迟
python eval/run_eval.py --config configs/v2_tier1.json --tag baseline

# 3. 起服务
python -m uvicorn api:app --port 8000
curl -X POST localhost:8000/ask -H 'Content-Type: application/json' \
     -d '{"question":"Flink 的 Watermark 解决什么问题？"}'
```

**离线自检（不花一分钱额度，38 项断言）：**

```bash
python tests/test_p0_offline.py      # 25 项：切分元信息、语料指纹、索引复用与重建
python tests/test_p1_retriever.py    # 13 项：重复文本映射、无兜底、短路可见
```

---

## 评测怎么做的（可复核，不靠人眼挑）

评测集每条给三个字段，由脚本机械解析成 gold：

```json
{"question": "mapred-site.xml 里怎么让 MapReduce 跑在 YARN 上？",
 "section":  "关键配置文件清单",
 "anchors":  ["mapreduce.framework.name"],
 "source":   "L01-04"}
```

`eval/resolve_gold.py` 判定规则：**章节命中 ∧ 全部锚点命中**。
人复核的是"这一章 + 这几个词是不是答案所在"，而不是在 457 块里挑出一块。
当前 20 题全部锁定，0 条需要人工兜底。

指标：`hit@10`（向量召回）、`hit@topn`（流水线最终结果）、`MRR@topn`，延迟分段计时。

**带 LLM 的配置单次数字不可信** —— 同一配置重跑三次得到 `0.80 / 0.85 / 0.85`。
所有结论都按多次取样给区间。

---

## 实验记录

```
tag                 hit@10            hit@3   MRR                p50(s)
plain rewrite       0.80/0.85/0.85    0.70    0.675/0.675/0.650   1.43
protected rewrite   0.85/0.85/0.85    0.70    0.675/0.650/0.675   1.52
strict rewrite      0.85/0.90/0.85    0.70    0.675 × 3           1.43
rewrite off         0.95/0.95         0.80    0.742/0.742         0.82   ← 当前最优
```

全链路分段（457 块，5 题，中位）：

```
rewrite      0.609 s  12.6%
query_embed  0.307 s   6.3%
vector_scan  0.028 s   0.6%   ← 这一层不值得优化
rerank       0.383 s   7.9%
generate     3.174 s  65.5%   ← 唯一的大头
```

---

## 工程问题记录

三个**会让评测数字失真、但不影响使用者感受**的缺陷，都是先测出来才修的：

1. **用 `text` 当字典键回查 chunk**。457 块里有 2 组重复文本，后者覆盖前者，
   rerank 结果会静默映射到另一个 chunk。改为全程传下标。
2. **映射失败时 `return chunks[0]` 兜底**。这是最坏的失败模式 —— 错得完全正常。
   改为抛异常并带上返回内容前缀。
3. **`recall_k <= rerank_top_n` 时精排被静默跳过**。跑消融时 `rerank on/off` 两组
   会变成同一组却看不出来。现在发 `RuntimeWarning`，每块带 `rerank_applied`。

---

## 已知限制

- **31 篇语料不足以断言泛化性**。所有结论只限定在**配置之间的相对差异**上，
  不宣称绝对召回水平。
- 20 题里 15 题是术语型，分布有偏 —— 这可能会放大"改写有害"这一结论。
- `section` 元信息目前取"块起始处最近的标题"。当前一节末尾的代码块溢出时，
  标题会落到下一块中间，导致该块被前文污染（已观测到 1 例：`动态表`，gold 排第 49）。
  修法是 heading-aware chunking，尚未实施。
- 生成阶段未接入，评测只覆盖检索链路。

---

## 这个项目是怎么来的

最初是课程作业的第二阶段收官练习：5 篇课程笔记 + 5 层架构 + 数答案关键词的"评测"。

2026-11 在保留分层骨架的前提下重做：

- 语料换成 31 篇个人工程笔记，冻结快照 + manifest 保证可复现
- 评测从"数答案里的关键词"换成 gold chunk 上的 `hit@k` / `MRR`
- 参数可注入，消融可脚本化
- 修掉上面三处会让数字失真的实现缺陷

`docs/` 里 5 篇原始课程笔记保留，作对照用。

顺带发现：旧版 README 的「返回示例」用的是「Kafka 的 LEO 和 HW 是什么」，
而 `docs/` 与 `kb_corpus/` 里**没有任何 LEO / HW 的定义**（全库 0 处命中）——
那段示例答案（包括 `"snippet": "LEO 表示日志最后偏移..."`）只能是模型补的，不是检索出来的。
该示例已从本文档移除；`eval_set.json` 的 5 道题本身都可回答，没有这个问题。

---

## 下一步

```
1  heading-aware chunking     在标题处强制切块，一块只属一个小节
2  扩到 60 题                 20 术语 / 20 跨文档多跳 / 20 口语化
3  chunk_size 256 / 1000 消融
4  BM25 + 混合检索（RRF）     向量检索在关键词型问题上会漏（已观测 1 例）
```

---

## 目录结构

```
knowledge_base/
├─ config.py               ① 配置层（RAGConfig，可注入）
├─ loader.py               ② 数据层（切分 + 元信息 + 语料指纹）
├─ retriever.py            ③ 检索层（召回 + rerank）
├─ generator.py            ④ 生成层（4 种改写模式）
├─ api.py                  ⑤ 服务层（FastAPI）
├─ configs/                实验配置（v2_tier1.json）
├─ eval/                   评测集、gold 解析、跑批脚本、结果 CSV
├─ bench/                  分段耗时探针 + 基线落档
├─ tests/                  38 项离线断言（零 API 调用）
├─ tools/make_corpus.py    从个人笔记生成冻结语料快照
├─ kb_corpus.manifest.json 语料清单（路径 + sha256 + 字符数，无内容）
├─ docs/                   原始 5 篇课程笔记（保留作对照）
├─ evaluator_demo.py       旧版评测（只统计答案关键词覆盖，已被 eval/ 取代）
└─ kb_store/               向量库（自动生成，gitignore）
```

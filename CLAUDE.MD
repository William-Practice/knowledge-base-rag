# CLAUDE.MD — 本项目的 agent 入口（Claude Code 侧）

> **公开事实源：本目录的 `README.md`**。本文件是入口副本；冲突时以 `README.md` 与
> `eval/results/summary.csv` 为准。（本地工作副本可能另有 `AGENTS.md`，不随仓库分发。）
>
> **文件名注意**：Claude Code 只认小写 `.md` —— 本目录的 `CLAUDE.md` 是指向本文件的软链，
> 所以它会正常加载；`CLAUDE.MD` 这个大写后缀是给人看的规范名。

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

## 3. Claude Code 专有提醒

```
· 它会自动读 ./CLAUDE.md（本仓库里是指向 CLAUDE.MD 的软链）与 ~/.claude/CLAUDE.md
· 默认会对每条命令请求审批；批量改动前先说清"只做什么、不要做什么"
· 改完必须让它贴 `python tests/*.py` 的原始输出，不能接受"测试通过"
· 长任务交给它时，把 eval 命令写进简报：改了检索逻辑就要重跑 60 题并对照 summary.csv
· 一个工作区只跑一个 agent —— 两个 Claude/Codex 同改会静默互相覆盖
```

---

## 4. 常用命令与验收

```bash
python loader.py --config configs/v2_tier1.json                 # 建库 / 复用
python loader.py --config configs/v2_tier1.json --dry-run       # 只切分，不调 API
python eval/run_eval.py --config configs/v2_tier1.json --rewrite-mode off --tag baseline
python tests/test_p0_offline.py | tail -2                       # 期望 25/25
python tests/test_p1_retriever.py | tail -2                     # 期望 13/13
git status --porcelain | grep -c '\.md$'                        # 期望 0
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
2026-11-09  建立。与 AGENT.md、HARNESS.MD 同批，均为 AGENTS.md 的入口副本。
```

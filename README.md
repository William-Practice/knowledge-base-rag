# 个人知识库问答系统（Phase 2 RAG 收官项目）

基于 **5 层模块化架构** 的 RAG 知识库问答系统：Query 重写 → 向量召回 Top10 → Rerank 精排 Top3 → GLM 生成，FastAPI 提供服务。

## 技术栈

| 层 | 文件 | 技术 |
|----|------|------|
| ① 配置层 | `config.py` | 模型/路径/参数集中管理，支持 .env |
| ② 数据层 | `loader.py` | 加载 docs/ 多文档 → 切分 → 向量化建库（JSON 持久化） |
| ③ 检索层 | `retriever.py` | 向量召回 Top10（embedding-2）+ Rerank 精排 Top3（rerank-pro） |
| ④ 生成层 | `generator.py` | Query 重写 + Prompt 拼接 + GLM 生成（答案 + 来源） |
| ⑤ 服务层 | `api.py` | FastAPI：`/ask` + `/health` |

Embedding 与 LLM 均走智谱开放平台（embedding-2 / glm-4v-flash / rerank-pro），全部纯 HTTP/JSON，无 LangChain/Chroma 重依赖。

## 安装

```bash
# Python 3.10+；本项目使用 venv: helloGLM/bin/python
pip install fastapi uvicorn

# 配置 API Key（二选一）
export ZHIPU_API_KEY='你的智谱key'          # 或
echo 'ZHIPU_API_KEY=你的智谱key' > .env
```

## 运行

```bash
# 1. 建库（自动：docs/ 5 个文档 → 切分 → 向量化 → kb_store/）
python loader.py

# 2. 启动 API 服务
python -m uvicorn api:app --reload --port 8000

# 3. 调用接口
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Kafka 的 LEO 和 HW 是什么？"}'

# 健康检查
curl http://localhost:8000/health

# 浏览器接口文档
# http://localhost:8000/docs
```

## 返回示例

```json
{
  "question": "Kafka 的 LEO 和 HW 是什么？",
  "rewritten": "Kafka 中 LEO 和 HW 的含义是什么？",
  "answer": "LEO（Log End Offset）是分区日志末尾的下一条偏移量...",
  "sources": [
    {"file": "Kafka分区副本消费组.md", "chunk": 3, "score": 0.9823,
     "snippet": "LEO 表示日志最后偏移..."}
  ]
}
```

## 目录结构

```
knowledge_base/
├─ .env.example          # Key 配置模板（勿提交真实 key）
├─ config.py             # ① 配置层
├─ loader.py             # ② 数据层
├─ retriever.py          # ③ 检索层
├─ generator.py          # ④ 生成层
├─ api.py                # ⑤ 服务层
├─ evaluator_demo.py     # 评测示例（跑 eval_set.json）
├─ docs/                 # 知识库文档（5 篇技术笔记）
├─ eval_set.json         # 5 道评测题
└─ kb_store/             # 向量库（自动生成，勿提交）
```

## 评测

```bash
python evaluator_demo.py    # 用 eval_set.json 的 5 道题逐题问答
```

## 说明

- 知识库内容为个人大数据学习笔记（Kafka/ZooKeeper/Hadoop/Flink/Spark SQL）
- 重建向量库：删除 `kb_store/` 后重跑 `python loader.py`

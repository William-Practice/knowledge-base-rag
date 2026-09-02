# L33：Flink 集群部署 总结

> 日期：2026-07-20
> 版本：Flink 1.17.2, Scala 2.12, Standalone 模式

---

## 一、Flink vs Spark Streaming

| 对比项 | Flink | Spark Streaming |
|--------|-------|----------------|
| **计算模型** | 真正的流（逐条处理） | 微批（Micro-batch） |
| **延迟** | 毫秒级 | 秒级 |
| **状态管理** | 内置强大状态后端 | 依赖外部存储 |
| **Event Time** | 原生支持 | 需要额外配置 |
| **SQL** | Table API / SQL | Structured Streaming |
| **国内流行度** | ✅ 实时计算首选 | 批处理为主 |

---

## 二、Flink 集群部署

### Standalone 模式（开发环境）

```bash
# 下载
wget https://dlcdn.apache.org/flink/flink-1.17.2/flink-1.17.2-bin-scala_2.12.tgz
tar xzf flink-1.17.2-bin-scala_2.12.tgz -C /opt/
ln -sf /opt/flink-1.17.2 /opt/flink
```

### 配置（/opt/flink/conf/flink-conf.yaml）

```yaml
jobmanager.rpc.address: localhost
jobmanager.rpc.port: 6123
jobmanager.memory.process.size: 1024m
taskmanager.memory.process.size: 1024m
taskmanager.numberOfTaskSlots: 2
parallelism.default: 2
rest.port: 8083                 # 避免和 Spark Worker 冲突
```

### 启动/停止

```bash
# 启动集群
/opt/flink/bin/start-cluster.sh

# 停止集群
/opt/flink/bin/stop-cluster.sh

# Web UI
http://localhost:8083
```

---

## 三、运行第一个 Flink 任务

### Batch 模式（批处理）

```bash
/opt/flink/bin/flink run /opt/flink/examples/batch/WordCount.jar
```

### Streaming 模式（Socket 流）

```bash
# 终端1：启动 netcat
nc -lk 9999

# 终端2：提交 Flink 任务
/opt/flink/bin/flink run \
  /opt/flink/examples/streaming/SocketWindowWordCount.jar \
  --port 9999

# 在终端1输入：
hello flink
hello world
flink streaming
```

### 查看任务

```bash
/opt/flink/bin/flink list           # 运行中的任务
/opt/flink/bin/flink list -a       # 所有任务（含已完成）
```

---

## 四、Flink 架构

```
           Client
             │
             ▼
    ┌── JobManager (Master) ──┐
    │  • 调度任务              │
    │  • 检查点（Checkpoint）   │
    │  • 故障恢复              │
    └────────────────────────┘
             │
    ┌────────┴────────┐
    ▼                 ▼
TaskManager 1    TaskManager 2
(2 slots)        (2 slots)
    │                 │
  task              task
  task              task
```

### 核心组件

| 组件 | 说明 | Web UI 端口 |
|------|------|------------|
| **JobManager** | 主节点，负责任务调度、Checkpoint | 8083 |
| **TaskManager** | 从节点，执行任务 | — |
| **Task Slot** | TaskManager 的资源单元 | — |

---

## 五、部署模式对比

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| **Standalone** | Flink 自带集群 | 开发测试 |
| **YARN** | 基于 Hadoop YARN | ✅ **生产常用** |
| **Kubernetes** | 基于 K8s | 容器化环境 |
| **Local** | 单进程 | 本地调试 |

---

## 六、相关命令速查

```bash
# 启动/停止集群
/opt/flink/bin/start-cluster.sh
/opt/flink/bin/stop-cluster.sh

# 提交任务
/opt/flink/bin/flink run -c com.example.Main my-job.jar

# 提交任务（带参数）
/opt/flink/bin/flink run \
  -c com.example.Main my-job.jar \
  --input hdfs://path/to/input \
  --output hdfs://path/to/output

# 取消任务
/opt/flink/bin/flink cancel <job-id>

# 查看任务列表
/opt/flink/bin/flink list
/opt/flink/bin/flink list -a

# Web UI
open http://localhost:8083
```

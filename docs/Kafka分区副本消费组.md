# L19：Kafka 分区 + 副本 + 消费组 总结

> 日期：2026-05-22
> 环境：单 broker（broker.id=1），Topic: `lesson19-demo`（2 partitions, 1 replica）

---

## 一、分区（Partition）

### 概念
- Kafka 将 Topic 物理拆分为多个 Partition
- 每个 Partition 是一个有序、不可变的日志（log）
- 消息通过 **Partitioner** 决定落入哪个分区

### 分区策略
| 策略 | 说明 | 适用场景 |
|------|------|---------|
| **DefaultPartitioner**（Sticky） | 粘性分区，批量填满一个分区再切下一个 | 吞吐优先 |
| **RoundRobinPartitioner** | 轮询，均匀分布 | 负载均衡 |
| **自定义 Partitioner** | 按 key/value 内容路由 | 业务分区（如按用户ID、按长度） |

### 实操结果
```
Producer → lesson19-demo（2 partitions）
→ msg-1   → partition 0
→ msg-2   → partition 1
→ msg-3   → partition 0
→ msg-4   → partition 1
→ msg-5   → partition 0
→ msg-6   → partition 1
```
消息轮询分配到各分区，实现并行读写。

### 查询分区信息
```bash
kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic <topic名>
```

---

## 二、副本（Replication）

### 概念
- 每个 Partition 可以有多个副本（Replica）
- **Leader**：负责读写请求
- **Follower**：从 Leader 同步数据

### ISR（In-Sync Replicas）
- 跟 Leader 保持同步的副本集合
- 只有 ISR 中的副本才有资格接替 Leader
- `replica.lag.time.max.ms`（默认 10s）——超过此时间未同步则踢出 ISR

### ACK 语义（生产端）
| acks | 说明 | 数据可靠性 | 性能 |
|------|------|-----------|------|
| `acks=0` | 发完即走，不确认 | ❌ 可能丢数据 | 🚀 最快 |
| `acks=1` | Leader 确认写入 | ✅ 默认 | ⚡ 快 |
| `acks=-1`（all） | ISR 全部确认 | ✅✅ **最安全** | 🐢 较慢 |

> 当前环境单 broker，ReplicationFactor=1，只能演示分区概念。
> 多 broker 集群时可用 `--replication-factor 2` 创建副本。

---

## 三、消费组（Consumer Group）

### 概念
- 多个 Consumer 实例组成一个 Group
- **一个分区只能被组内的一个 Consumer 消费**
- Consumer 数量 ≤ 分区数（超出部分闲置）

### 示意图
```
Topic（3 partitions）
├── Partition 0  ←  Consumer A
├── Partition 1  ←  Consumer B
└── Partition 2  ←  Consumer C
         ↑
    同一个 Group
```

### 关键参数
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `group.id` | null | 消费组名称 |
| `enable.auto.commit` | true | 是否自动提交 offset |
| `auto.offset.reset` | latest | 无 offset 时从哪开始消费 |
| `session.timeout.ms` | 45000 | Consumer 心跳超时 |

### Offset 提交方式
| 方式 | 说明 |
|------|------|
| **自动提交** | 每隔 `auto.commit.interval.ms` 自动提交（可能重复消费） |
| **手动同步** `commitSync()` | 阻塞直到提交成功 |
| **手动异步** `commitAsync()` | 不阻塞，可搭配回调 |
| **存 Redis** | 自主管理 offset，L18 的做法 |

---

## 四、补充：Kafka Eagle（EFAK）监控

如果装了 Kafka Eagle（课程 L15），可以在 Web UI 上直观看到：
- Topic 分区分布
- Consumer Group Lag
- Broker 状态

---

## 五、面试常考题

1. **Kafka 为什么快？**
   - 顺序写磁盘（比随机写快 6000x）
   - 零拷贝（sendfile）
   - 批量压缩发送

2. **分区数越多越好吗？**
   - ❌ 不是。分区过多 → 文件句柄多、Leader 选举慢、端到端延迟增加
   - 建议：分区数 ≈ 消费者线程数 × 2

3. **ISR 的作用？**
   - 保证数据一致性。只有 ISR 中的副本可以成为新 Leader

4. **消息丢失怎么排查？**
   - Producer：检查 `acks` 设置
   - Broker：检查 `min.insync.replicas`
   - Consumer：检查 `enable.auto.commit` + offset

5. **如何保证消息有序？**
   - 单个分区内有序
   - 全局有序 → 只能设 1 个分区（牺牲吞吐）
   - 业务有序 → 按业务 key 路由到同一分区

---

## 六、相关命令速查

```bash
# 创建 topic（指定分区数和副本数）
kafka-topics.sh --bootstrap-server localhost:9092 \
  --create --topic test --partitions 3 --replication-factor 1

# 查看 topic 详情
kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic test

# 查看消费组
kafka-consumer-groups.sh --bootstrap-server localhost:9092 --list

# 查看消费组详情（含 Lag）
kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --describe --group my-group

# 重置消费组 offset
kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --group my-group --topic test --reset-offsets --to-earliest --execute
```

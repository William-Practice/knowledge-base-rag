# L30：Spark SQL 总结

> 日期：2026-07-04
> 环境：Spark 3.5.0 Standalone + HDFS

---

## 一、Spark SQL 是什么

- 把 SQL 翻译成 Spark RDD / DataFrame 计算任务
- 比直接写 RDD 代码更简洁，**数据分析师也能用**
- 兼容 Hive SQL 语法

### 核心概念

```
HDFS/本地文件  →  DataFrame（分布式表） →  SQL 查询 →  结果
                    ↑
              SparkSession 入口
```

---

## 二、DataFrame 与 SQL 的关系

| 概念 | 类比关系 |
|------|---------|
| **DataFrame** | 类似关系型数据库的**表** |
| **Row** | 表中的**一行** |
| **Column** | 表中的**一列** |
| **SparkSession** | 类似 JDBC **Connection** |
| **TempView** | 临时表（仅当前 session 可见） |

---

## 三、Spark SQL 操作流程

### 3.1 读取文件创建 DataFrame

```scala
// Spark Shell 中
val df = spark.read
  .option("header", "false")       // 是否有表头
  .option("inferSchema", "true")   // 自动推断类型
  .csv("hdfs://localhost:9000/input/data.csv")
  .toDF("id", "name", "score", "gender")

df.show()  // 打印数据
df.printSchema()  // 打印结构
```

### 3.2 注册临时视图

```scala
df.createOrReplaceTempView("students")
```

### 3.3 执行 SQL 查询

```scala
// 全部数据
spark.sql("SELECT * FROM students").show()

// 聚合查询
spark.sql("""
  SELECT gender, ROUND(AVG(CAST(score AS INT)), 2) AS avg_score
  FROM students GROUP BY gender
""").show()

// 条件过滤 + 排序
spark.sql("""
  SELECT name, score FROM students
  WHERE CAST(score AS INT) >= 90
  ORDER BY CAST(score AS INT) DESC
""").show()
```

### 3.4 保存结果

```scala
result.write.mode("overwrite").csv("hdfs://localhost:9000/output/result")
```

---

## 四、DataFrame API 与 SQL 对比

### SQL 风格

```scala
spark.sql("SELECT name, score FROM students WHERE score > 80").show()
```

### DataFrame API 风格（等价）

```scala
df.select("name", "score")
  .where(col("score") > 80)
  .show()
```

---

## 五、支持的读/写格式

| 格式 | 读 | 写 |
|------|----|-----|
| CSV | ✅ | ✅ |
| JSON | ✅ | ✅ |
| Parquet | ✅ **推荐** | ✅ **压缩率高** |
| ORC | ✅ | ✅ |
| JDBC (MySQL) | ✅ | ✅ |
| Hive 表 | ✅ | ✅ |

---

## 六、常用 SQL 函数

### 聚合函数
| 函数 | 说明 | 示例 |
|------|------|------|
| `COUNT()` | 计数 | `SELECT gender, COUNT(*) FROM students GROUP BY gender` |
| `AVG()` | 平均值 | `AVG(CAST(score AS INT))` |
| `SUM()` | 求和 | `SUM(CAST(score AS INT))` |
| `MAX() / MIN()` | 最大/最小 | `MAX(score)` |
| `ROUND()` | 四舍五入 | `ROUND(AVG(score), 2)` |

### 类型转换
```scala
CAST(score AS INT)       // 转整型
CAST(timestamp AS DATE)   // 转日期
CAST(price AS DOUBLE)     // 转浮点
```

### 条件函数
```scala
CASE WHEN score >= 90 THEN '优秀'
     WHEN score >= 60 THEN '及格'
     ELSE '不及格' END AS level
```

---

## 七、相关命令速查

```bash
# 启动 Spark Shell（交互式 SQL）
spark-shell --master spark://localhost:7077

# 启动时禁用 Hive 支持（避免依赖 MySQL）
spark-shell --master spark://localhost:7077 \
  --conf spark.sql.catalogImplementation=in-memory

# 用 spark-submit 提交 SQL 应用
spark-submit --master spark://localhost:7077 \
  --class com.example.SparkSQLDemo my-app.jar

# 查看 Spark Web UI
curl http://localhost:4040  # 当前应用的 SQL 执行计划
```

---

## 八、面试常考题

1. **DataFrame 和 RDD 的区别？**
   - DataFrame 有 schema（表结构），执行效率更高
   - RDD 是 Java/Scala 对象，更灵活但更慢
   - DataFrame 通过 Catalyst Optimizer 优化执行计划

2. **Spark SQL 怎么处理小文件问题？**
   - 写文件时用 `repartition()` 或 `coalesce()` 控制输出文件数
   - 读取时 Spark 会自动合并小文件

3. **Spark 和 Hive 的关系？**
   - Hive 是纯 SQL on MapReduce（慢）
   - Spark SQL 是 SQL on Spark（内存计算，快 10~100 倍）
   - 两者 SQL 语法基本兼容

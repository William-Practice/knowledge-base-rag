以下是根据我们实际操作整理的 **ZooKeeper 完全分布式集群配置过程总结**，供您笔记参考。

---

## ZooKeeper 集群配置总结（三节点）

### 环境准备
- 三台虚拟机：`bigdata-live01-01`（主节点）、`bigdata-live01-02`、`bigdata-live01-03`
- 用户：`wry`（具备 sudo 权限）
- JDK 8 已安装
- 三节点可通过主机名互相通信（`/etc/hosts` 已配置）
- SSH 免密登录已配置（主节点到从节点，但执行 sudo 仍需密码）

---

### 一、下载与解压（在一台节点上完成，后分发）

1. **下载 ZooKeeper 二进制包**（使用国内镜像加快速度）  
   ```bash
   wget https://mirrors.aliyun.com/apache/zookeeper/zookeeper-3.8.4/apache-zookeeper-3.8.4-bin.tar.gz -P /opt
   ```

2. **解压并重命名**  
   ```bash
   cd /opt
   sudo tar -xzf apache-zookeeper-3.8.4-bin.tar.gz
   sudo mv apache-zookeeper-3.8.4-bin zookeeper
   sudo chown -R wry:wry /opt/zookeeper
   ```

3. **创建数据目录和日志目录**  
   ```bash
   cd /opt/zookeeper
   mkdir data logs
   ```

---

### 二、配置 ZooKeeper 集群

1. **生成配置文件 `zoo.cfg`**  
   ```bash
   cp /opt/zookeeper/conf/zoo_sample.cfg /opt/zookeeper/conf/zoo.cfg
   nano /opt/zookeeper/conf/zoo.cfg
   ```
   修改/添加以下内容：
   ```properties
   dataDir=/opt/zookeeper/data
   dataLogDir=/opt/zookeeper/logs
   clientPort=2181
   server.1=bigdata-live01-01:2888:3888
   server.2=bigdata-live01-02:2888:3888
   server.3=bigdata-live01-03:2888:3888
   ```

2. **创建 `myid` 文件（每节点不同）**  
   - 主节点：`echo 1 > /opt/zookeeper/data/myid`  
   - 从节点1：`echo 2 > /opt/zookeeper/data/myid`  
   - 从节点2：`echo 3 > /opt/zookeeper/data/myid`  

   > 注意：`myid` 必须与 `zoo.cfg` 中 `server.x` 的编号一致。

---

### 三、分发 ZooKeeper 到其他节点

由于权限问题，**采用手动登录各从节点执行**（避免 `sudo` 远程密码交互）。

1. **在主节点打包完整目录**  
   ```bash
   cd /opt
   tar -czf /tmp/zookeeper-full.tar.gz zookeeper
   ```

2. **在从节点上执行（手动登录）**  
   ```bash
   # 登录从节点1 (bigdata-live01-02)
   ssh wry@192.168.56.102
   scp wry@192.168.56.101:/tmp/zookeeper-full.tar.gz /tmp/
   sudo tar -xzf /tmp/zookeeper-full.tar.gz -C /opt
   sudo chown -R wry:wry /opt/zookeeper
   # 创建 myid
   echo 2 | sudo tee /opt/zookeeper/data/myid
   exit
   ```
   对从节点2（IP 192.168.56.103）重复操作，`myid` 设为 3。

3. **同步 `zoo.cfg` 到从节点**（若打包时已包含，则无需再同步）

---

### 四、启动 ZooKeeper 集群

依次在三个节点上执行：
```bash
/opt/zookeeper/bin/zkServer.sh start
```

检查状态：
```bash
/opt/zookeeper/bin/zkServer.sh status
```
应有一个 `leader`，两个 `follower`。

---

### 五、测试客户端连接

任意节点执行：
```bash
/opt/zookeeper/bin/zkCli.sh -server bigdata-live01-01:2181
```

测试命令：
```
ls /
create /test "hello"
get /test
quit
```

---

### 六、常见问题及解决

| 问题                                     | 原因                                    | 解决方法                                        |
| ---------------------------------------- | --------------------------------------- | ----------------------------------------------- |
| `scp: No such file or directory`         | 目标路径不存在                          | 手动登录创建目录或使用完整路径                  |
| `sudo: a terminal is required`           | SSH 远程执行 sudo 需要终端              | 手动登录每个节点执行，或配置免密 sudo           |
| `zkServer.sh: No such file or directory` | 从节点缺少 `bin` 目录                   | 重新分发完整 ZooKeeper 目录                     |
| `Error contacting service`               | myid 配置错误、主机名解析失败、端口被占 | 检查 `myid`、`/etc/hosts`、日志 `zookeeper.out` |
| 端口冲突                                 | 防火墙或已有服务占用 2181/2888/3888     | 关闭防火墙 `sudo ufw disable`，或修改端口       |

---

通过以上步骤，您成功搭建了一个三节点的 ZooKeeper 集群，为后续 Kafka、HBase 等组件提供服务。


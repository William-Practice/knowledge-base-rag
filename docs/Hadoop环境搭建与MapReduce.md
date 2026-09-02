# **核心就业生态技术完整就业课**笔记

## 第1-4课 linux环境配置、原理和单机环境部署、分布式环境部署和MapReduce、改代码跑MR和集群启动Shell

## 预备

### 宿主机配置

| 项目              | 配置                                                         |
| ----------------- | ------------------------------------------------------------ |
| 操作系统          | Ubuntu 24.04.3 LTS x86_64                                    |
| CPU               | 12th Gen Intel i7-12700H (20核)                              |
| 内存              | 32 GB                                                        |
| 硬盘              | 512 GB (实际可用)                                            |
| VirtualBox 版本   | 7.0+                                                         |
| Host-Only 网卡 IP | 192.168.56.1                                                 |
| 角色              | 客户端（不参与集群服务）                                     |
| 已装软件          | JDK 8、JDK 17、Hadoop 3.2.0（客户端配置指向集群）、Hive 3.1.0、Maven 3.3.9、IntelliJ IDEA |
| 网络连通性        | 可 ping 通 192.168.56.101/102/103                            |

### 虚拟机配置

**主节点**

| 项目         | 配置                                                   |
| ------------ | ------------------------------------------------------ |
| 操作系统     | Ubuntu 22.04.5 Server                                  |
| 主机名       | bigdata-live01-01                                      |
| IP 地址      | 192.168.56.101（Host-Only），10.0.3.15（NAT）          |
| CPU          | 2 核（VirtualBox 分配）                                |
| 内存         | 2 GB                                                   |
| 硬盘         | 10 GB（动态分配）                                      |
| 用户名       | wry                                                    |
| 密码         | 123456（示例）                                         |
| 角色         | NameNode、SecondaryNameNode、ResourceManager           |
| Hadoop 版本  | 3.2.0（安装于 /opt/hadoop）                            |
| JDK 版本     | OpenJDK 1.8.0_xxx（/usr/lib/jvm/java-8-openjdk-amd64） |
| 数据目录     | /opt/hadoop/data/namenode、/opt/hadoop/data/datanode   |
| 配置文件位置 | /opt/hadoop/etc/hadoop/                                |
| 启动脚本     | /home/wry/hadoop-cluster.sh（自写）                    |
| 监听端口     | 9870（HDFS Web）、8088（YARN Web）                     |
| SSH 免密     | 已配置到自身及两个从节点                               |

**从节点**

| 项目 | 配置 |
|------|------|
| 操作系统 | Ubuntu 22.04.5 Server |
| 主机名 | bigdata-live01-02、bigdata-live01-03 |
| IP 地址 | 192.168.56.102（Host-Only），10.0.3.15（NAT）；192.168.56.103（Host-Only），10.0.3.15（NAT） |
| CPU | 2 核 |
| 内存 | 2 GB |
| 硬盘 | 10 GB |
| 用户名 | wry |
| 密码 | 123456 |
| 角色 | DataNode、NodeManager |
| Hadoop 版本 | 3.2.0（从主节点复制） |
| JDK 版本 | OpenJDK 1.8.0_xxx |
| 数据目录 | /opt/hadoop/data/datanode |
| SSH 免密 | 接受主节点免密登录 |

###  拓扑图

![](./Screenshot 2026-04-08 063808.png)

所有虚拟机通过 **Host-Only 网络** 互通，并通过 **NAT 网卡** 访问外网（下载软件包）。宿主机通过 Host-Only 网络与虚拟机通信，作为客户端提交作业。

### 关键配置文件清单

| 文件                                     | 所在节点     | 核心配置                                          |
| ---------------------------------------- | ------------ | ------------------------------------------------- |
| `/etc/hosts`                             | 所有节点     | 包含 `192.168.56.101 bigdata-live01-01` 等        |
| `/etc/netplan/00-installer-config.yaml`  | 各节点       | 静态 IP（enp0s3） + DHCP（enp0s8）                |
| `/opt/hadoop/etc/hadoop/core-site.xml`   | 主节点及同步 | `fs.defaultFS=hdfs://bigdata-live01-01:9000`      |
| `/opt/hadoop/etc/hadoop/hdfs-site.xml`   | 主节点及同步 | `dfs.replication=2`，数据目录路径                 |
| `/opt/hadoop/etc/hadoop/yarn-site.xml`   | 主节点及同步 | `yarn.resourcemanager.hostname=bigdata-live01-01` |
| `/opt/hadoop/etc/hadoop/mapred-site.xml` | 主节点及同步 | `mapreduce.framework.name=yarn`                   |
| `/opt/hadoop/etc/hadoop/workers`         | 主节点       | 列出 `bigdata-live01-02` 和 `bigdata-live01-03`   |
| `/home/wry/hadoop-cluster.sh`            | 主节点       | 集群启停脚本                                      |

##  硬件环境配置

### 虚拟机的配置

下载VirtualBox虚拟机，Windows/Mac版直接到官网下载，Debian就直接

```bash
sudo apt update
sudo apt install virtualbox -y
```

在网络管理器（Ctrl+H）中，设置Host-Only网络`vboxnet0`，网络掩码`255.255.255.0`，IP地址为`192.168.56.1`，同时关闭DHCP服务器以免**随机生成ip地址**导致无法通信。

在官网**下载 Ubuntu Server 22.04**，内存仅占用200M左右。设置虚拟机内存为2GB，磁盘20GB，分配给虚拟机两张网卡，网卡1为连接上面已经建立的`vboxnet0`网络，网卡2连接NAT方便下载Hadoop环境包。之后将Ubuntu镜像插入虚拟机1，安装系统。

### 配置网络

安装系统时在网络设置界面选择enp0s3网卡，选择 **Edit IPv4** → **Manual**（手动），填写以下信息：

- **Subnet**：`192.168.56.0/24`
- **Address**：`192.168.56.101`（主节点可设为 101，从节点 102、103）
- **Gateway**：`192.168.56.1`
- **Name servers**：`8.8.8.8`（或 `192.168.56.1` 如果宿主机提供 DNS 转发）
- **Search domains**：留空或填 `local`

之后继续安装。在用户创建界面输入以下信息：![](/home/wuruiyang/桌面/Downloads./image.png)

| 字段                  | 填写内容                     |
| :-------------------- | :--------------------------- |
| Your name             | `Hadoop`（或任意，如 `KFK`） |
| Your server's name    | `bigdata-live01-01`          |
| Pick a username       | wry                          |
| Choose a password     | `123456`                     |
| Confirm your password | `123456`                     |

三个节点使用**相同的用户名和密码**，便于后续 SSH 免密登录配置。之后完成安装过程后，输入`poweroff`命令关机。

### 克隆虚拟机

1. 在 VirtualBox 主界面，右键点击 `live01-01` → **克隆**。

2. 弹出窗口：

   - **名称**：`live01-02`
   - **路径**：默认或自定义
   - **克隆类型**：选择 **完全克隆**（Full clone）
   - **MAC 地址策略**：选择 **为所有网卡重新生成 MAC 地址**（避免冲突）

3. 点击 **克隆**，等待完成。

4. 重复上述步骤，再克隆一个 `live01-03`。

5. 启动任何一个从节点，登陆，默认用户名为`wry`，密码`123456`。然后`sudo hostnamectl set-hostname bigdata-live01-02`.

### 网络配置（二）

   ```bash
   sudo nano /etc/netplan/00-installer-config.yaml
   ```

   ```yaml
   network:
     version: 2
     renderer: networkd
     ethernets:
       enp0s3:
         dhcp4: no
         addresses:
           - 192.168.56.101/24
         nameservers:
           addresses: [8.8.8.8, 8.8.4.4]
       enp0s8:
         dhcp4: yes
   ```

   ```bash
   sudo netplan generate
   sudo netplan apply
   ```

一定要让`enp0s3`**关闭DHCP功能**否则大数据实验没法用。`enp0s8`是NAT转换，是可以联网的。
   同样的对于两个从节点：

   ```yaml
   network:
     version: 2
     renderer: networkd
     ethernets:
       enp0s3:
         dhcp4: no
         addresses:
           - 192.168.56.102/24   # 03 节点改为 103
         nameservers:
           addresses: [8.8.8.8, 8.8.4.4]
       enp0s8:
         dhcp4: yes
   ```

   ```bash
   sudo netplan generate
   sudo netplan apply
   ```

最终网络变成这样的。
   ![image-20260408151509137](/home/wuruiyang/.config/Typora/typora-user-images/image-20260408151509137.png)

之后在3台虚拟机互相执行`ping`命令能通就行。

## 软件环境配置

### 下载并配置JDK和Hadoop环境变量

在克隆虚拟机之前，在主节点运行：

```bash
apt update
apt install -y openjdk-8-jdk
java -version   # 验证
# 进入 /opt 目录
cd /opt
# 使用 wget 下载（Apache 归档）
wget https://archive.apache.org/dist/hadoop/common/hadoop-3.2.0/hadoop-3.2.0.tar.gz
cd /opt
tar -xzf hadoop-3.2.0.tar.gz
mv hadoop-3.2.0 /opt/hadoop   # 可选重命名
echo 'export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64' | tee -a /etc/profile.d/java.sh
echo 'export PATH=$JAVA_HOME/bin:$PATH' | tee -a /etc/profile.d/java.sh
chmod +x /etc/profile.d/java.sh
source /etc/profile
echo 'export HADOOP_HOME=/opt/hadoop' >> /etc/profile
echo 'export PATH=$PATH:$HADOOP_HOME/bin:$HADOOP_HOME/sbin' >> /etc/profile
source /etc/profile
hadoop version
```

### 宿主如何和虚拟机连接？

```bash
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
ip a | grep inet
ssh root@192.168.56.101
```

### SSH免密登录，虚拟机之间如何连接？

```bash
ssh-keygen -t rsa
ssh-copy-id wry@bigdata-live01-01
ssh-copy-id wry@bigdata-live01-02
ssh-copy-id wry@bigdata-live01-03
ssh bigdata-live01-01
ssh bigdata-live01-02
ssh bigdata-live01-03
```

不需要密码登录。

之后**配置hosts**，只要输入对方机器名称就可以连接了。

```bash
sudo nano /etc/hosts

127.0.0.1 localhost
192.168.56.101 bigdata-live01-01
192.168.56.102 bigdata-live01-02
192.168.56.103 bigdata-live01-03

# The following lines are desirable for IPv6 capable hosts
::1     ip6-localhost ip6-loopback
fe00::0 ip6-localnet
ff00::0 ip6-mcastprefix
ff02::1 ip6-allnodes
ff02::2 ip6-allrouters

```

### 配置 Hadoop 目录下的4个重要文件

#### `/opt/hadoop/etc/hadoop/core-site.xml`

```xml
<configuration>
    <property>
        <name>fs.defaultFS</name>
        <value>hdfs://bigdata-live01-01:9000</value>
    </property>
</configuration>
```

#### `hdfs-site.xml`

```xml
<configuration>
    <property>
        <name>dfs.replication</name>
        <value>2</value>
    </property>

    <property>
        <name>dfs.namenode.name.dir</name>
        <value>file:/opt/hadoop/hdfs/name</value>
    </property>

    <property>
        <name>dfs.datanode.data.dir</name>
        <value>file:/opt/hadoop/hdfs/data</value>
    </property>

</configuration>
```

#### 配置`yarn-site.xml`并启动 YARN

```xml
<configuration>

    <!-- 指定 ResourceManager 在主节点 -->
    <property>
        <name>yarn.resourcemanager.hostname</name>
        <value>bigdata-live01-01</value>
    </property>

    <!-- 启用 MapReduce shuffle 服务 -->
    <property>
        <name>yarn.nodemanager.aux-services</name>
        <value>mapreduce_shuffle</value>
    </property>

</configuration>
```

之后：

```bash
scp /opt/hadoop/etc/hadoop/yarn-site.xml wry@bigdata-live01-02:/home/wry/
scp /opt/hadoop/etc/hadoop/yarn-site.xml wry@bigdata-live01-03:/home/wry/
ssh bigdata-live01-02
sudo mv /home/wry/yarn-site.xml /opt/hadoop/etc/hadoop/

ssh bigdata-live01-03
sudo mv /home/wry/yarn-site.xml /opt/hadoop/etc/hadoop/

start-yarn.sh
# 然后 jps 会多出 ResourceManager、NodeManager。
```

#### `mapred-site.xml`

```xml
```

之后执行：

```bash
scp $HADOOP_HOME/etc/hadoop/core-site.xml wry@bigdata-live01-02:/home/wry/
scp $HADOOP_HOME/etc/hadoop/core-site.xml wry@bigdata-live01-03:/home/wry/
ssh bigdata-live01-02
sudo mv /home/wry/core-site.xml /opt/hadoop/etc/hadoop/
hdfs namenode -format
start-dfs.sh
start-yarn.sh
```

之后在所有节点上：

```bash
mkdir -p /home/wry/hadoop/tmp
mkdir -p /home/wry/hadoop/hdfs/name
mkdir -p /home/wry/hadoop/hdfs/data
```

#### 测试 Hadoop

```bash
hdfs dfs -mkdir -p /user/wry
echo "hello hadoop" > test.txt
hdfs dfs -put test.txt /user/wry/
hdfs dfs -ls /user/wry/
```

当需要添加从节点时，克隆虚拟机并修改 IP、主机名，然后在主节点配置 `workers` 文件（`/opt/hadoop/etc/hadoop/workers`），同步配置文件，启动集群。

### 分发配置

```bash
scp -r $HADOOP_HOME wry@bigdata-live01-02:/home/wry/
scp -r $HADOOP_HOME wry@bigdata-live01-03:/home/wry/
```

之后

```bash
nano $HADOOP_HOME/etc/hadoop/workers
bigdata-live01-02
bigdata-live01-03
nano $HADOOP_HOME/etc/hadoop/hdfs-site.xml
rm -rf /opt/hadoop/hdfs
mkdir -p /opt/hadoop/hdfs/name
mkdir -p /opt/hadoop/hdfs/data
sudo chown -R wry:wry /opt/hadoop/hdfs
hdfs namenode -format #只在主节点
start-dfs.sh #只在主节点
start-yarn.sh #只在主节点
wry@bigdata-live01-01:~$ jps
14339 Jps
13637 NameNode
13864 SecondaryNameNode
14041 ResourceManager
wry@bigdata-live01-01:~$ ssh bigdata-live01-02 jps
6888 NodeManager
6747 DataNode
7179 Jps
```

这样**拓扑图**中的目标就实现了。

## 修改 MapReduce 源码

### 宿主机的操作

在宿主机器上打开编辑工具，输入以下代码：

```java
package org.example;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.io.IntWritable;
import org.apache.hadoop.io.Text;
import org.apache.hadoop.mapreduce.Job;
import org.apache.hadoop.mapreduce.Mapper;
import org.apache.hadoop.mapreduce.Reducer;
import org.apache.hadoop.mapreduce.lib.input.FileInputFormat;
import org.apache.hadoop.mapreduce.lib.output.FileOutputFormat;

import java.io.IOException;
import java.util.StringTokenizer;

public class MapReduce {

    // 自定义 Mapper：按逗号分割单词
    public static class CommaTokenizerMapper extends Mapper<Object, Text, Text, IntWritable> {
        private final static IntWritable one = new IntWritable(1);
        private Text word = new Text();

        public void map(Object key, Text value, Context context) throws IOException, InterruptedException {
            // 使用逗号作为分隔符
            StringTokenizer itr = new StringTokenizer(value.toString(), ",");
            while (itr.hasMoreTokens()) {
                String token = itr.nextToken().trim();  // 去掉可能的空格
                word.set(token);
                context.write(word, one);
            }
        }
    }

    // 自定义 Reducer（也可以直接使用 org.apache.hadoop.mapreduce.lib.reduce.IntSumReducer）
    public static class IntSumReducer extends Reducer<Text, IntWritable, Text, IntWritable> {
        private IntWritable result = new IntWritable();

        public void reduce(Text key, Iterable<IntWritable> values, Context context)
                throws IOException, InterruptedException {
            int sum = 0;
            for (IntWritable val : values) {
                sum += val.get();
            }
            result.set(sum);
            context.write(key, result);
        }
    }

    public static void main(String[] args) throws Exception {
        Configuration conf = new Configuration();
        Job job = Job.getInstance(conf, "word count with comma");
        job.setJarByClass(MapReduce.class);

        // 使用自定义 Mapper
        job.setMapperClass(CommaTokenizerMapper.class);
        job.setCombinerClass(IntSumReducer.class);   // Combiner 复用 Reducer
        job.setReducerClass(IntSumReducer.class);

        job.setOutputKeyClass(Text.class);
        job.setOutputValueClass(IntWritable.class);

        FileInputFormat.addInputPath(job, new Path(args[0]));
        FileOutputFormat.setOutputPath(job, new Path(args[1]));

        System.exit(job.waitForCompletion(true) ? 0 : 1);
    }
}
```

然后在终端输入` mvn clean package`打包成JAR文件。之后运行

```bash
scp /home/wuruiyang/IdeaProjects/hadoop_test/target/hadoop_test-1.0-SNAPSHOT.jar wry@192.168.56.101:/home/wry/
hadoop jar /home/wry/hadoop_test-1.0-SNAPSHOT.jar org.example.MapReduce /user/wry/input_comma /user/wry/output_comma
```

注意：上次如果运行失败必须删除输出目录：

```bash
# 删除旧的输出目录
hdfs dfs -rm -r /user/wry/output_comma
```

## 编写集群统一启停脚本

```bash
#!/bin/bash

# 设置 Hadoop 守护进程用户（根据实际用户修改，本例为 wry）
export HDFS_NAMENODE_USER=wry
export HDFS_DATANODE_USER=wry
export HDFS_SECONDARYNAMENODE_USER=wry
export YARN_RESOURCEMANAGER_USER=wry
export YARN_NODEMANAGER_USER=wry

# 节点列表（主节点和从节点）
MASTER="bigdata-live01-01"
SLAVES="bigdata-live01-02 bigdata-live01-03"

# Hadoop 安装路径
HADOOP_HOME=/opt/hadoop

case $1 in
    start)
        echo "== Starting HDFS =="
        ssh $MASTER "$HADOOP_HOME/sbin/start-dfs.sh"
        echo "== Starting YARN =="
        ssh $MASTER "$HADOOP_HOME/sbin/start-yarn.sh"
        ;;
    stop)
        echo "== Stopping YARN =="
        ssh $MASTER "$HADOOP_HOME/sbin/stop-yarn.sh"
        echo "== Stopping HDFS =="
        ssh $MASTER "$HADOOP_HOME/sbin/stop-dfs.sh"
        ;;
    status)
        echo "== Master node processes =="
        ssh $MASTER "jps | grep -E 'NameNode|SecondaryNameNode|ResourceManager'"
        for slave in $SLAVES; do
            echo "== Slave $slave processes =="
            ssh $slave "jps | grep -E 'DataNode|NodeManager'"
        done
        ;;
    *)
        echo "Usage: $0 {start|stop|status}"
        exit 1
        ;;
esac
```

## 总结：已测试的功能

- [x] HDFS 文件上传/下载/查看
- [x] YARN 资源管理界面访问
- [x] 修改后的 MapReduce 程序（逗号分隔 WordCount）在集群上成功运行
- [x] 宿主机通过 `hdfs dfs -ls /` 访问 HDFS
- [x] 宿主机通过 `hadoop jar` 提交作业到集群
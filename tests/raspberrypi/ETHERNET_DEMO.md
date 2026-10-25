# Pi 1B 以太网验收 demo

## 当前可执行测试

使用开发版固件，将板载 RJ45 接入可信且启用 DHCP 的局域网。无需外接 USB 网卡。
通过串口粘贴 `ethernet_demo.py`，或在根文件系统可用时保存为 `/ethernet_demo.py`：

```python
import ethernet_demo
ethernet_demo.run(timeout_ms=30000, observe_ms=30000)
```

demo 查询 `network.LAN()`，等待链路和 DHCP，输出 IPv4、掩码、网关、DNS。
取得地址后，在同一局域网的电脑运行 `ping <板端地址>`。demo 等待期间让 Circle
协作网络任务继续运行；必须看到电脑的 ping 回复才算 ICMP 实板验收通过。
没有网卡或 DHCP 超时会抛异常，不会打印虚假 PASS。

故障时可手动读取驱动日志（每次最多 1024 字节，重复至空）：

```python
import machine
print(machine.network_info())
print(machine.logs())
```

此 demo 不修改 SD 内容、不访问公网、不创建 socket。它不证明 TCP、UDP、DNS
解析或 TLS 完成。`active(True)` 目前仅接受已初始化的接口，不会重试硬件初始化；
停用和静态地址设置尚未实现。根 FAT 挂载失败不会妨碍通过 REPL 粘贴执行。

## UDP echo 往返验收（已编译接入，待实板验证）

板端保存并运行 `udp_echo_demo.py`（或通过 REPL 粘贴），先确认 DHCP 成功：

```python
import udp_echo_demo
udp_echo_demo.run(port=5005, packets=3)
```

电脑端在同一可信局域网运行：

```text
python mpynn/tests/raspberrypi/udp_echo_client.py 板端IPv4地址 --port 5005
```

客户端发送三个二进制报文（14、256、1283 字节），验证回包来源和完整内容，
全部匹配才输出 `UDP_ECHO_ROUNDTRIP_PASS`。板端每次接收超时15秒，电脑端5秒；
应及时启动客户端。超时或数据不匹配是失败，不能算通过。脚本不写SD。
当前仅支持数字IPv4、通配bind与sendto/recvfrom；不支持TCP、域名、connected
UDP或空报文发送。主机桩测试通过不等同于此实板往返测试通过。

## 后续 socket/TLS 验收要求

- 本机局域网 TCP echo：小块 recv 拼回原数据、部分 send、断开 EOF 与 RST 区分。
- UDP echo：保持报文边界，处理截断、无报文时 EAGAIN 和有限等待超时。
- 连接、监听、poll、关闭及软重启资源回收；无服务器时不能无限卡住 REPL。
- TLS 客户端验证受信 CA 和服务器名称；错误 CA、错误主机名、过期证书必须失败。
- TLS 使用真正硬件熵；未设置可信 UTC 时不能假称证书有效。
- 不以 CERT_NONE、跳过证书日期校验或 ticks 充当随机数通过验收。

当前这些 socket/TLS 项目是待实现与待验收项，不是可运行功能清单。

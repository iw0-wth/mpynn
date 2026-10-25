# mpynn 独立演示与实板验收

本目录用于**用户演示**；不引用开发测试目录。不要混用开发 test 脚本。
建议把 `demo` 目录（含 `__init__.py`、`network` 子目录和 `ml.py`）复制到板端 `/demo`。ML/file-media 演示只读取 SD 上用户明确提供的模型、图片和 WAV 文件，不采集摄像头、不显示 IDE 预览、不联网、不自动写盘。
电脑配套脚本只在电脑上执行；不需要上传它来测试板子。

## 当前进度

- 已有实板证据：Pi 1B Rev2 / revision14 / 512MiB；此前锁定镜像的
  `f452e679...927b6e` 与用户输出匹配。**用户已确认 SD 卡读写正常。**
- 用户已确认基础 TCP echo 实板通过；尚未独立记录：多文件 Thonny 保存、完整断电持久性、
DHCP/UDP/DNS/HTTPS 以及 TCP 服务端的实板结果。SD“读写正常”不会被扩展成上述全部通过。
- 已实现并编译：RTC/time、f/t-string、冻结库、UDP/TCP基础收发与监听、DNS A、
  标准 ssl/mbedTLS、超时/poll/端点查询及诊断接口。
- 仍有工程缺口：socket 并非完整CPython/POSIX（部分选项/真实半关闭/IPv6），
  其它外设和实际AI后端未完整接入。显式TCP bind reservation、SO_TYPE/UDP SO_BROADCAST getsockopt和静态服务名已接入；更多选项、真实半关闭、IPv6仍未完整支持。
- 上游 `lib/` 只读；适配与工具产物均在端口层和项目 `build/`。

当前开发镜像（含ssl、静态网络、socket选项、严格地址、隐式listen及accept资源保护；新API需更新内核）：
- `../build/RPI1B/bin/kernel.img`：1,387,424 字节
- SHA-256：`4fefeedbd0f3dc4dedd493ba2fde07de7ac15b4ea45c93380413365a6ce062f1`
- build_id：`e74b1a787e3c4ed9b29cd003d73af8db53edf2aa8a21ea004d7e6896ff092ebf`
- 新增原生 `uml`/TFLM reference、ulab 4D、PNG/BMP/PNM 文件图像、WAV/PCM 文件音频。
  JPEG、摄像头/IDE 预览、麦克风硬件采集不在本次支持范围；实板 ML 尚待验收。

用户已验证的旧镜像和本轮新镜像结果需按各自build_id记录；不要将旧SD结果算作
新网络补丁实测。演示是独立SD文件，未冻结进固件，修改演示无需重刷内核。

## 文件与入口

| 文件 | 用途 | 导入后的显式入口 |
|---|---|---|
| board.py | 型号/版本/存储/根目录，只读 | `board.show()` |
| storage.py | 文件读写和冷启动持久性 | `inspect/roundtrip/prepare/verify_after_reboot/cleanup` |
| rtc.py | RTC/time一致性，可选手工设时 | `show/check/set_utc` |
| language.py | f/t-string和冻结库导入 | `language.run()` |
| network/lan.py | LAN9512/DHCP诊断 | `lan.run()` |
| network/udp.py | UDP二进制和空报文echo | `udp.client(host)` / `udp.server()` |
| network/tcp.py | TCP客户端/服务端echo及非阻塞握手 | `tcp.client(host)` / `tcp.server()` / `tcp.connect_nonblocking(host)` |
| network/options.py | 类型、广播许可和TCP_NODELAY设置/查询 | `options.run()`；不发送报文 |
| network/https.py | 默认HTTPS / CA验证 / 主动NTP | `https.run(url, ca_path=None)` / `https.sync_time()` |
| network/pc_echo.py | 电脑端UDP/TCP配套 | `python ... --help` |

### 1. ML、VFS 图片和 WAV/PCM 文件演示

先把用户自己的模型/媒体文件复制到 SD，例如：

```text
/hello_world_float.tflite
/red.png
/input.wav
```

然后执行：

```python
from demo import ml
print(ml.infer('/hello_world_float.tflite', 0.0))
print(ml.infer_callable('/hello_world_float.tflite', 0.25))
outputs = ml.image_tensor('/red.png', '/hello_world_float.tflite')
chunks = ml.stream_wav('/input.wav', samples=320)
print('chunks:', len(chunks), 'first_bytes:', len(chunks[0]) if chunks else 0)
```

说明：

- `infer()` 使用 ulab ndarray 输入，输出是独立 float ndarray 的数值。
- `infer_callable()` 验证 `__call__(bytearray, shape, dtype)` 输入契约。
- `image_tensor()` 支持当前 native `image` 文件子集：PNG、未压缩 BMP24/BMP32、PNM P1–P6；JPEG 会明确抛出 `NotImplementedError`。图片不需要特定分辨率或宽高比，但文件必须完整、格式合法、尺寸 1..8192，解码图像不超过 64 MiB；Normalization 会按模型输入 shape 缩放。
- `stream_wav()` 使用文件型 PCM16 WAV；没有 USB/I2S/ADC 实时采集。
- 这些入口均不自动写 SD、不访问摄像头、不联网，也不连接 IDE 预览。

### 2. 信息、RTC和语法

```python
from demo import board, rtc, language
board.show()
rtc.check()
language.run()
```

`rtc.check()`只读取及等待走时，不会校时。RTC每次冷启动从2000-01-01开始；
软件钟无电池保持。`language.py`包含t-string，需本固件或Python3.14才能解析。

### 2. SD文件演示（会写盘，必须显式同意）

SD已正常，不必为每个网络测试再执行写盘步骤。需要复核时先备份卡：

```python
from demo import storage
storage.inspect()
storage.roundtrip(write=True)  # 独占创建、读回、删除自己的演示文件
```

真正验证断电持久性：

```python
storage.prepare(write=True)  # 保留 /__mpynn_demo_persist__.bin
```

正常关闭文件和同步后，完全断电再上电：

```python
from demo import storage
storage.verify_after_reboot()  # 只读核对；必须确实冷启动才算持久性通过
storage.cleanup(confirm=True)
```

文件已存在会拒绝覆盖。异常后打印存储统计/日志并停止，不自动重试或删除。
`cleanup`只删除内容恰好匹配本演示的文件，未知或不完整文件不会自动删除。

### 3. DHCP

接入可信DHCP局域网：

```python
from demo.network import lan
lan.run()
```

记录板端IP，电脑ping该地址。默认网卡已由内核启动，`network.LAN()`注册Python NIC。
本轮新版固件增加静态IPv4与DHCP切换（旧镜像需升级；不支持 `active(False)`）：

```python
import network
nic = network.LAN()
# 先关闭现有TCP/UDP socket，避免旧连接保留旧本地地址
nic.ifconfig(('192.168.1.50', '255.255.255.0', '192.168.1.1', '8.8.8.8'))
print(nic.ifconfig())
# 或恢复DHCP；该调用仅发起新请求，须等待租约
nic.ifconfig('dhcp')
lan.run()  # 最多等待30秒
```

也可用 `lan.use_static(...)` 和 `lan.use_dhcp()`。静态地址必须符合你所在局域网并未被
其它设备占用；不会做自动冲突探测。配置仅在本次系统运行期间生效，冷启动恢复DHCP。
软重启保留内核网络状态；修改地址不会自动关闭已有socket。

### 4. UDP echo

电脑开服务，板端当客户端（先电脑后板端）：

```text
python mpynn/demo/network/pc_echo.py --protocol udp --mode server --host 0.0.0.0 --port 5005
```

```python
from demo.network import udp
udp.client('电脑IPv4')
```

反向（先板端后电脑，需在超时内启动）：

```python
udp.server(port=5005, packets=3)
```

```text
python mpynn/demo/network/pc_echo.py --protocol udp --mode client --host 板端IPv4 --port 5005
```

### 5. TCP echo

```text
python mpynn/demo/network/pc_echo.py --protocol tcp --mode server --host 0.0.0.0 --port 5006
```

```python
from demo.network import tcp
tcp.client('电脑IPv4')
```

非阻塞握手演示（先启动电脑TCP服务器；此演示不发送echo payload）：

```python
tcp.connect_nonblocking('电脑IPv4')
```

它验证 `connect` 的 EINPROGRESS、poll、SO_ERROR和peer查询；SO_ERROR=0但尚未就绪
不算连接成功。拒绝/超时会报告错误并关闭socket，不用close伪装半关闭。

真实写半关闭：电脑重新启动上面的单连接 TCP echo server，然后在板端执行：

```python
tcp.half_close('电脑IPv4')
```

它先发送 payload，再调用两次 SHUT_WR，检查新写入返回 EPIPE；随后继续读取完整
回显和对端 EOF，最后 close 释放资源。可在电脑抓包核对 FIN 时序；host 测试不等于
这项实板通过。SHUT_RD/SHUT_RDWR 同样支持，但未读 RX 会被主动丢弃。

反向：先在板端调用 `tcp.server()`，再运行：

```text
python mpynn/demo/network/pc_echo.py --protocol tcp --mode client --host 板端IPv4 --port 5006
```

临时端口监听：`tcp.server(port=0)`显式绑定临时端口；`tcp.server(port=None)`省略bind，
由listen隐式选端口。板端会打印实际端口，电脑的`--port`必须填写该值；板端IPv4用
`lan.run()`输出，监听地址0.0.0.0不是电脑连接的目标地址。

TCP/UDP demo都有有限等待和固定流量上限；服务器只服务有限报文/一个客户端，
不属于生产服务器。不在不可信网络长期暴露裸机板子。

#### TCP_NODELAY

```python
import network, socket
network.LAN()
s = socket.socket()
print(s.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY))  # 默认1
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 0)      # 显式启用Nagle
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)      # 关闭Nagle
s.close()
# 电脑端启动TCP echo server后，可复核连接前配置的两种值：
tcp.client('电脑IPv4', nodelay=0)
# 服务器只服务一个连接；下一次调用前重新启动电脑echo server
tcp.client('电脑IPv4', nodelay=1)
from demo.network import options
options.run()  # 不绑定、不发送，核对类型/广播/NODELAY和亚毫秒超时设置/查询
```

保留Circle历史默认值1：不额外等待未确认小包。显式0在已有未确认数据时延迟
小于MSS的报文；两种值都遵守发送窗口、拥塞窗口和背压。连接前设置会在建连成功后应用，
监听器的显式配置会传给accepted child。设置失败保留旧值，不在setter中立即发送。
选项演示只证明设置与查询一致，小包时序还需实板抓包验证。
`settimeout()`采用毫秒分辨率，正数向上取整：例如0.0001秒保存为0.001秒，
不会意外进入非阻塞模式。只有0表示非阻塞，None表示无限等待；实际等待精度需板端记录。

### 6. DNS和默认HTTPS（遵循上游 requests）

```python
from demo.network import resolver
resolver.local()  # None/AI_PASSIVE/numeric-only flags，不联网
resolver.invalid_endpoints()  # bind/connect/sendto严格拒绝异常IPv4/端口，无NIC选择/报文
resolver.resolve('你的测试域名', 'https')  # 显式IPv4 DNS查询
```

`getaddrinfo(None, port, ..., AI_PASSIVE)`返回0.0.0.0，用于监听绑定；无PASSIVE返回
127.0.0.1，仅验证地址选择，不表示Circle支持loopback通信。`port=None`为端口0。
AI_NUMERICHOST只接受严格四段IPv4，不启动DNS；AI_NUMERICSERV禁止服务名，仅接受
数字端口、十进制字符串或None。未知flags报错；IPv6尚未实现。
普通getaddrinfo也严格匹配完整IPv4：无效纯数字/点地址报EINVAL且不查询DNS；
带字母后缀的主机名完整交给DNS，不截取数字IP前缀。

```python
import network, socket
network.LAN()
print(socket.getaddrinfo('你的测试域名',443,socket.AF_INET,socket.SOCK_STREAM))
from demo.network import https
https.run('https://你的服务器/')
```

默认使用上游 `CERT_NONE`：流量加密，**不验证服务器证书身份**，不要求正确RTC/CA。
访问用户自己选定的服务器；演示不会在import时自动请求公网。

### 7. 完整证书验证（用户主动校时和配置CA）

```python
https.sync_time('pool.ntp.org')  # 显式联网、修改RTC；可换自己的NTP服务器
https.run('https://你的服务器/', ca_path='/ca.pem')
```

提前把受信CA的PEM或DER文件保存为 `/ca.pem`（不要保存私钥到本目录）。
也可先用 `rtc.set_utc(...)` 手工设置当前UTC。完整验证使用 `CERT_REQUIRED`、CA及
URL实际主机名；错误CA/主机名/有效期应失败，不降级到CERT_NONE。
NTP本身不是认证时间源；当前RTC/证书时间范围受2038边界限制。

完整检查项及当前证据见 **TEST_CHECKLIST.md**。开发时主机测试仍留在原测试目录，
它们不能当作用户demo，也不等同于实板通过。

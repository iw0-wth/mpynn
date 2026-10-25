# mpynn 独立用户演示

本目录用于**用户演示**；不引用开发测试目录。开发测试与板级 smoke/bench 已统一归属 workspace 根目录的 `tests/raspberrypi`，与 `mpynn` 同级；测试脚本保留在测试树，不作为导入即运行的 demo 搬入本目录。
建议把整个 `demo` 目录（含各层 `__init__.py` 和模型资产）复制到板端 `/demo`。示例按 `system/`、`network/`、`ai/` 分类，操作指南在 `docs/`。ML/file-media 演示只读取 SD 上用户明确提供的模型、图片和 WAV 文件，不采集摄像头、不显示 IDE 预览、不联网、不自动写盘。
电脑配套脚本只在电脑上执行；不需要上传它来测试板子。

## 开箱运行的 VC4 加速项目

[稠密特征评分器](ai/vc4_acceleration/README.md) 已配齐 `model.tflite`、确定性输入和参考数据。
把整个 demo 复制到 SD 后即可运行，不需要自行准备模型：

```python
from demo.ai import vc4_acceleration
result = vc4_acceleration.run()
```

它用同一 FP32 2048→1024 模型比较 CPU/VC4，展示评分、平均耗时和实测加速比，检查两组
输入的所有输出，并从本次诊断标记之后确认 packed16 单dispatch完成。模型约8 MiB，
需要当前 packed16 VC4 固件；导入不执行推理，运行不联网、不写盘，结束保留日志。
历史相同模型在700/250基线约6.56x；示例始终打印本次实测值，不预置性能结论。

## 英文文本分类项目

[textcls](ai/textcls/README.md) 配齐已修正的 TFLM 模型、词表与 11 类标签，直接运行：

```python
from demo.ai import textcls
textcls.run()
```

自定义文本可调用 `Classifier.classify()`，详见项目说明。该模型是小词表演示，返回原始
分类评分而非概率，默认走 reference CPU；不要把它当成任意文本识别器或 VC4 加速基准。

## 状态与历史记录

以下镜像大小、哈希和旧反馈保留作历史记录，并非当前构建的固定身份。使用 `board.show()` 记录实际运行的 build_id，再与该镜像的构建记录核对；修改独立 demo 不会更新内核身份。原生 UML/TFLM、ulab、文件媒体和可选 VC4 已有实现；用户模型是否使用 QPU 要看运行时 dispatch 日志，不能由 backend 名称或计时推断。

- 已有实板证据：Pi 1B Rev2 / revision14 / 512MiB；此前锁定镜像的
  `f452e679...927b6e` 与用户输出匹配。**用户已确认 SD 卡读写正常。**
- 用户已确认基础 TCP echo 实板通过；尚未独立记录：多文件 Thonny 保存、完整断电持久性、
DHCP/UDP/DNS/HTTPS 以及 TCP 服务端的实板结果。SD“读写正常”不会被扩展成上述全部通过。
- 已实现并编译：RTC/time、f/t-string、冻结库、UDP/TCP基础收发与监听、DNS A、
  标准 ssl/mbedTLS、超时/poll/端点查询及诊断接口。
- 仍有工程缺口：socket 并非完整CPython/POSIX；更多选项/flags 和其它外设尚未完整支持，IPv6不在当前范围。真实TCP半关闭、显式TCP bind reservation、SO_TYPE/UDP SO_BROADCAST getsockopt和静态服务名已接入；代码/主机验证不能替代实板记录。
- 上游 `lib/` 只读；适配与工具产物均在端口层和项目 `build/`。

此前开发镜像记录（含ssl、静态网络、socket选项、严格地址、隐式listen及accept资源保护；新API需更新内核）：
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
| system/board.py | 型号/build_id/存储/内存/时钟/可用machine API，只读 | `board.show()` |
| system/storage.py | 文件读写和冷启动持久性 | `inspect/roundtrip/prepare/verify_after_reboot/cleanup` |
| system/rtc.py | RTC/time一致性，可选手工设时 | `show/check/set_utc` |
| system/language.py | f/t-string和冻结库导入 | `language.run()` |
| ai/media.py | 标量模型、文件图像、WAV/PCM | `infer/infer_callable/image_tensor/stream_wav` |
| ai/vc4.py | 用户模型与ndarray，reference/VC4输出及计时 | `vc4.run(model_path, inputs, backend='vc4')` / `vc4.compare(model_path, inputs)` |
| ai/vc4_acceleration/ | 配齐模型的稠密评分器，直接展示加速与本次GPU执行证据 | `vc4_acceleration.run()` |
| ai/textcls/ | 配齐模型、词表和11类标签的英文文本分类 | `textcls.run()` / `textcls.Classifier().classify(text)` |
| docs/ | 板端操作、历史进度和检查清单 | 阅读对应 Markdown |
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
from demo.ai import media
print(media.infer('/hello_world_float.tflite', 0.0))
print(media.infer_callable('/hello_world_float.tflite', 0.25))
outputs = media.image_tensor('/red.png', '/hello_world_float.tflite')
chunks = media.stream_wav('/input.wav', samples=320)
print('chunks:', len(chunks), 'first_bytes:', len(chunks[0]) if chunks else 0)
```

说明：

- `infer()` 使用 ulab ndarray 输入，输出是独立 float ndarray 的数值。
- `infer_callable()` 验证 `__call__(bytearray, shape, dtype)` 输入契约。
- `image_tensor()` 支持当前 native `image` 文件子集：PNG、未压缩 BMP24/BMP32、PNM P1–P6；JPEG 会明确抛出 `NotImplementedError`。图片不需要特定分辨率或宽高比，但文件必须完整、格式合法、尺寸 1..8192，解码图像不超过 64 MiB；Normalization 会按模型输入 shape 缩放。
- `stream_wav()` 使用文件型 PCM16 WAV；没有 USB/I2S/ADC 实时采集。
- 这些入口均不自动写 SD、不访问摄像头、不联网，也不连接 IDE 预览。

### 用户模型的 reference / VC4 演示

使用支持 `ml.Model(..., backend=...)` 的当前固件。先准备用户自己的 `.tflite` 文件，并按模型输入 shape/dtype 构造 ulab ndarray；下面仅举单输入 FP32、shape 为 `(1, 4)` 的模型，数值和维度应按自己的模型调整：

```python
from ulab import numpy as np
from demo.ai import vc4
x = np.array([[0.25, -0.5, 0.125, 1.0]], dtype=np.float)
result = vc4.run('/my_model.tflite', x, backend='reference',
                 arena_size=2 * 1024 * 1024, warmup=1, repeat=5)
print(result['outputs'], result['avg_us'])
both = vc4.compare('/my_model.tflite', [x], warmup=2, repeat=10,
                   rearm=True)
print(both['reference']['outputs'], both['vc4']['outputs'])
```

- `run(..., backend='reference'/'vc4')` 返回 `outputs`、`total_us`、`avg_us`、`warmup`、`repeat` 和 `backend`；多输入模型传 `[x0, x1, ...]`。不生成固定输入、不读取 golden，不下载模型或写文件。输入 dtype 由原生 Model 检查，返回 ndarray 在模型释放后仍归用户持有。
- `compare()` 对相同输入分别新建 reference 和 VC4 模型，返回两份结果及观察到的 `speedup`；输出由用户按模型需求比较，没有固定误差阈值或自动 PASS。reference 表示禁用 VC4 的当前 CPU 路径。
- 计时仅覆盖重复 `predict()`，不含模型加载、Prepare、warmup、输出打印及日志读取；每次预测的输出分配包含在内。保持 repeat 足够短以避免 ticks 环绕歧义；很短的模型可能计为零，此时比值为 `None`。结果受时钟、模型与运行状态影响，不预先承诺加速。
- 每次运行都在 `finally` 中 `deinit()`、恢复先前的 `machine.vc4()` 并回收 GC，包括输入形状不匹配、推理中断和异常。切换会在模型构造前完成；不要在并行推理期间改变进程级开关。
- 默认运行结束后只调用一次 `machine.logs(clear=False, limit=16384)`，显示保留日志快照，可能含以前的记录；不消费日志，不循环重复前缀。旧固件若不支持非消费读取则提示更新，不退回消费 API。`diagnostics=False` 可关闭，`vc4.snapshot()` 可手工查看。
- `rearm=True` 显式调用 `machine.vc4_reset_diagnostics()`，重新开放有界诊断采样，但不清空旧日志；默认不重置。旧固件缺少该 API 时给出错误，可用 `rearm=False` 或升级固件。诊断采样状态不会随机器开关恢复。
- VC4 只是允许卸载；算子、FP32 FC 形状、运行时时钟门槛、内存或其它运行条件仍可使模型走 CPU。观察当前运行的 dispatch-complete / FC timing 日志确认 QPU 使用；单凭输出一致、backend 标签或速度比不能确认硬件卸载。

### 2. 信息、RTC和语法

```python
from demo.system import board, rtc, language
board.show()
rtc.check()
language.run()
```

`rtc.check()`只读取及等待走时，不会校时。RTC每次冷启动从2000-01-01开始；
软件钟无电池保持。`language.py`包含t-string，需本固件或Python3.14才能解析。

### 2. SD文件演示（会写盘，必须显式同意）

SD已正常，不必为每个网络测试再执行写盘步骤。需要复核时先备份卡：

```python
from demo.system import storage
storage.inspect()
storage.roundtrip(write=True)  # 独占创建、读回、删除自己的演示文件
```

真正验证断电持久性：

```python
storage.prepare(write=True)  # 保留 /__mpynn_demo_persist__.bin
```

正常关闭文件和同步后，完全断电再上电：

```python
from demo.system import storage
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

## 原板级脚本与现有 demo 的覆盖关系

下表记录原 `mpynn/tests/raspberrypi` 板级脚本的用户用法去向。原 smoke、断言、固定模型/golden、主机回归和端口 VC4 smoke/bench 保留为 workspace `tests/raspberrypi` 中的开发测试；本目录复用已有入口，避免复制一套自动运行测试。

| 原脚本/主题 | 用户演示入口 | 范围 |
|---|---|---|
| `network_smoke.py`、`ethernet_demo.py` | `network.lan.run/use_static/use_dhcp` | DHCP、状态与静态IPv4；显式调用才等待网络 |
| `udp_echo_client.py`、`udp_echo_demo.py` | `network.udp.client/server` + `network.pc_echo` | 有界UDP二进制/空报文echo及电脑配套 |
| `tcp_client_demo.py`、`tcp_server_demo.py` | `network.tcp.client/server/connect_nonblocking/half_close` | 有界TCP交互、poll和半关闭 |
| `dns_smoke.py`、`network_socket_contract.py` | `network.resolver`、`network.options` | 显式DNS查询、地址/选项演示；开发契约断言保留测试树 |
| `tls_client_demo.py` | `network.https.run(url, ca_path=...)`、`sync_time` | 用户URL与CA路径，主动校时；不在导入时联网 |
| `sd_smoke.py`、`thonny_smoke.py` 的文件用法 | `storage.inspect/roundtrip/prepare/verify_after_reboot/cleanup` | 显式写盘开关和独占文件；Thonny/REPL协议及冷启动步骤仍由用户单独验证 |
| `rtc_smoke.py`、`time_smoke.py` | `rtc.show/check/set_utc` | 读时、走时和显式手工设时；无电池保持 |
| `syntax_smoke.py`、`frozen_libs_smoke.py` | `language.run` | 固件语法与冻结库 |
| `machine_smoke.py` 的信息查询 | `board.show` | 只读报告 unique_id、频率、内存和API是否存在；不配置GPIO、不屏蔽IRQ、不启动WDT或总线 |
| 端口 `ml_smoke.py`、VC4 smoke/bench | `ml`、`vc4.run/compare` | 用户模型/媒体；固定fixture、golden和硬件验收仍是开发测试 |

完整检查项及历史证据见 [docs/TEST_CHECKLIST.md](docs/TEST_CHECKLIST.md)。开发测试统一位于 workspace 根目录 `tests`，不能当作用户demo，也不等同于实板通过。

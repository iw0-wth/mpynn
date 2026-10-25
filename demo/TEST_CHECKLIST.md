# mpynn 用户演示测试清单

状态说明：**已确认**仅指已有实板反馈；“已编译/主机验证”不等于实板通过。
每次测试请记录 `board.show()` 的 build_id、实际输出和失败 traceback。ML/文件媒体入口见 `demo.ml`；它只读用户提供的 SD 文件，不采集摄像头、不联网、不自动写盘。
本目录独立于开发测试目录，不要将开发 test 文件批量上传到板端。

| # | 项目 | 当前证据 | 操作 / 判定 |
|---|---|---|---|
| 1 | Pi 1B Rev2 / 固件身份 | 已确认 | 用户报告 model B R2、revision14、512MiB、匹配的 build_id |
| 2 | SD/FAT 根目录读写 | 已确认用户反馈“读写没有问题” | `storage.roundtrip(write=True)` 可选复核；不要重复格式化 |
| 3 | Thonny 保存多个文件 / 冷启动持久性 | 待单独记录 | 保存两个不同非空脚本，关闭文件后重连；完全断电再读回并运行 |
| 4 | SD 冷启动持久性 | 待单独记录 | `storage.prepare(write=True)` →安全断电→启动→`verify_after_reboot()`；确认后清理 |
| 5 | RTC / time | 已实现、主机验证；待板端记录 | `rtc.show()` / `rtc.check()`；默认2000年，走时一致；软件钟不掉电保存 |
| 6 | f-string / t-string / 冻结库 | 已编译；待板端记录 | `language.run()` 输出 LANGUAGE_FROZEN_LIBRARIES_OK |
| 7 | LAN9512 / DHCP / 静态地址切换 | 新固件已接入；待板端记录 | `lan.run()`；关闭socket后 `lan.use_static(...)`、电脑ping静态IP，再 `lan.use_dhcp()` 获取租约 |
| 8 | UDP 客户端 | 已实现、主机验证；待实板 | 电脑 UDP server；板端 `udp.client(电脑IPv4)`；检查二进制与空报文 |
| 9 | UDP 服务端 | 已实现、主机验证；待实板 | 板端 `udp.server()`；电脑 UDP client；校验来源/内容，有限超时 |
| 10 | TCP 客户端 | 已实现，用户已实板 echo 通过 | 电脑 TCP server；板端 `tcp.client(电脑IPv4)`；sendall/小缓冲读取及端点 |
| 11 | TCP 服务端 | 已实现；客户端实板路径已通过，服务端独立记录待补 | 板端 `tcp.server()`；电脑 TCP client；accept/EOF及关闭 |
| 12 | DNS IPv4 A | 已实现、主机验证；待实板 | `socket.getaddrinfo(域名,443,socket.AF_INET,socket.SOCK_STREAM)`；非数字IP实际查询 |
| 13 | 默认 HTTPS / requests | 标准 CERT_NONE 默认；真实TLS内存握手通过；待实板 | `https.run('https://你选择的服务器/')`；无需校时；不验证服务器身份 |
| 14 | 用户主动 NTP | 冻结上游模块；待实板 | `https.sync_time()`；主动联网并修改RTC，非自动启动动作 |
| 15 | 完整 HTTPS 证书校验 | 真实mbedTLS内存握手通过；待实板 | 校时+提供受信CA文件；`https.run(url,ca_path='/ca.pem')` |
| 16 | TLS 负向验证 | 主机验证通过；待实板 | 完整验证模式用错误CA、错误主机名或错误日期，必须失败；失败不记为PASS |
| 17 | 超时 / 非阻塞 / poll | 主机验证；待板端记录 | 零超时无数据只接受EAGAIN；有限时间内返回；Ctrl-C可中断 |
| 18 | 软重启资源回收 | 已实现；待板端压力记录 | 关闭/软重启后重复创建UDP/TCP，不泄漏句柄；网卡DHCP无需重建 |
| 19 | TCP_NODELAY/Nagle | 已实现；待实板配置/抓包记录 | `options.run()`核对；显式0等待未确认小包，1不等待；默认1保留历史Circle行为 |
| 20 | resolver None/AI标志 | 已实现；待板端记录 | `resolver.local()`无DNS验证；PASSIVE选0.0.0.0，NUMERICHOST/NUMERICSERV禁止名称查询 |
| 21 | machine surface gate | Pin/GPIO/I2C/SPI/WDT已主机验证；Timer/PWM/UART等仍禁用 | `test_machine_surface_host.py`确认硬件入口；SoftI2C/SoftSPI及未实现类不暴露 |
| 24 | machine WDT | 1–15秒、Start式feed、ownership/deinit/soft-reset已主机/ARM验证；待实板 | `machine.WDT(timeout=5)`；不得用 `Restart()`，实板验证feed和复位行为 |
| 23 | I2C/SPI transfer safety | 有界轮询、ownership、rollback已主机/ARM验证；待实板 | I2C BCM2/3；SPI BCM7/8/9/10/11；分别验证NACK/timeout、CS和软重启资源回收 |
| 22 | TCP half-close | native/packet/bridge/adapter主机验证；待实板 | 电脑TCP echo server；`tcp.half_close(电脑IPv4)`：SHUT_WR后EPIPE、完整回显、peer EOF，close释放资源 |
| 25 | ML float/int8/callback/callable | Windows MicroPython host + TFLM host archive通过；待Pi实板 | `demo.ml.infer()`、`infer_callable()`；记录模型输出和 callback/self identity |
| 26 | VFS image + Normalization | PNG/BMP/PNM native host/Windows runtime通过；待Pi实板 | `demo.ml.image_tensor('/red.png', model)`；JPEG应明确NotImplementedError |
| 27 | WAV/PCM file audio | native C/Windows runtime通过；待Pi实板 | `demo.ml.stream_wav('/input.wav')`；记录chunk长度、EOF和重复init/stop |

## 未完成的工程范围（不只是实板验收）

- socket 还不是完整 CPython/POSIX：部分选项/完整flags继续完善；真实TCP半关闭已有代码及主机验证，待实板。IPv6按决定排除；SO_TYPE、UDP SO_BROADCAST/SO_ERROR、TCP SO_ERROR/TCP_NODELAY、显式TCP bind reservation和静态常见服务名解析已接入。setsockopt支持项会在lazy NIC前完成校验。
- 静态IPv4/DHCP切换已接入新固件，待实板验证；不支持active(False)和自动IP冲突探测。
- Pin/GPIO、I2C、SPI、WDT 已有代码级主机/ARM证据；Timer/PWM/UART/Pin IRQ 仍禁用，待后续安全生命周期设计。I2C/SPI/WDT实板电气、喂狗和软重启矩阵由用户后续执行。
- 原生 UML/TFLM、ulab、文件 image、WAV/PCM audio 已接入并通过 ARM/主机验证；真实 Pi 推理、SD模型读取、文件媒体实板行为仍待用户验收。
- 不把默认 CERT_NONE 的加密请求记为“服务器身份验证通过”。
- 某项通过不会自动证明其它项；主机回归与实板结果必须分别记录。

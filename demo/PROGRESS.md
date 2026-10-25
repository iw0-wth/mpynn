# 当前移植进度（按证据分层）

## 已获得的实板反馈（仅以下项目）

- Pi 1B Rev2：`model='Raspberry Pi Model B R2'`、`revision=14`、`ram_mb=512`。
- 用户串口报告 build_id：`f452e679c8b429744863bc51958b2b4e2961f6276f2e03f4b84fe1cf15927b6e`，
  对应此前675352字节镜像，源码/运行镜像身份已确认。
- 用户确认 TCP 基础 echo 测试已跑通；当前记录限于基础 TCP 路径，不扩展为 TCP 服务端、DNS 或 HTTPS 全部通过。
- SD 初始统计 ready=1、read_requests=8、read_sectors=8、write_requests=0、failures=0。
  随后用户明确反馈：**“目前读写SD卡已经没有问题了”**。
- 这是用户确认的SD读写恢复，不把它扩展为新镜像网络测试、完整断电持久性或全部Thonny行为。

## 已接入并通过编译/主机验证

| 功能 | 实现范围 |
|---|---|
| Circle / VM | Pi1 ARMv6 hard-float、UART/friendly/raw REPL、软重启、GC/NLR桥接 |
| 根VFS | FAT启动SD挂载为可写 `/`，boot/main脚本；不公开 machine.SDCard，不自动格式化 |
| RTC/time | 软件UTC，从2000-01-01冷启动；datetime/init和time共用时钟，不掉电保持 |
| 语法/库 | f-string、t-string、memoryview；requests、ssl（mpy-lib包装tls）、ntptime、bisect、functools、itertools、contextlib、collections等冻结 |
| LAN | Circle USB/LAN9512/IPv4 DHCP；静态四元组/切回DHCP、路由ARP刷新、状态与诊断 |
| UDP | bind/connect/send/recv/sendto/recvfrom，空报文，广播选项、超时/poll、SO_ERROR消费并保留数据报、清理 |
| TCP | 异步connect、bind/listen/accept、send/recv/sendall总超时、缓存尾部、FIN/RST、端点查询、SO_ERROR、TCP_NODELAY/Nagle切换、SHUT_RD/WR/RDWR真实半关闭 |
| DNS | IPv4 A、TCP/UDP提示、五秒总等待和取消；不支持IPv6/全部getaddrinfo参数 |
| TLS | 标准ssl/mbedTLS、硬件RNG接口、默认CERT_NONE；可选CA/hostname/日期验证 |
| 诊断 | storage_info统计、machine.logs、board_info/build_id |
| 上游约束 | lib只读，覆盖源码在端口副本，mpy-cross/Circle输出在项目build中 |

最新完整主机回归：端口执行 **359项**、结果OK（其中1项可选UBSan跳过），AI **15项通过**。包含LAN配置、ssl包装、DHCP边界、SO_ERROR/NODELAY、shutdown和demo安全测试。这些是host/static证据，不是实板网络结果。
真实mbedTLS内存握手通过7项：默认无UTC成功、正确验证成功、错误CA/主机名/时间失败；
传输8705字节双向记录。内存通道不是Pi网卡或Python HTTPS端到端实测。

## 仍需完成

1. 实板记录网络DHCP、UDP/TCP/DNS和两种HTTPS模式，验证超时/Ctrl-C/软重启压力。
2. socket继续补其余可用选项及代码回归；真实TCP半关闭已接入端口自有Circle扩展并有native方法/PacketReceived、bridge和adapter主机测试，后续需Pi实测。IPv6明确不在当前范围。实板结果待用户后续提供，不再阻止代码开发；先完成IPv4 socket代码项再接入machine。
3. Pin/GPIO 已有 Circle bridge 和主机 baseline；I2C/SPI/IRQ/Timer/PWM/WDT 等新外设仍未接入。machine surface contract 只防止未实现类误暴露，不代表外设已实现；真实 AI 推理/ulab 也尚未完整接入。
4. 端口许可证、上游升级和其它Pi型号的ABI/硬件适配继续保持独立范围。

## 下一步建议

SD已正常，先运行只读 `board.show()`、`rtc.check()`、`language.run()`；
再用network演示与电脑配套验证LAN/UDP/TCP/HTTPS。无需再用开发test文件，也不需要
在每次网络测试前重复格式化/写卡。完整操作见README.md，逐项证据见TEST_CHECKLIST.md。

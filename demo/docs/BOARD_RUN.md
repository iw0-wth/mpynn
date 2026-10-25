# 当前镜像最短实板验证

启动串口日志中先确认内存行：

```text
Pi1B RAM: Circle low free <N> MiB, MicroPython GC <M> MiB, reserve 32 MiB
```

其中 `N` 是 Circle 在 SD/USB/network 初始化后的实际低地址 heap 剩余，`M=N-32`；这才是该板、该 GPU split 和该启动配置的真实可用数值，不是标称 512 MiB。REPL 中也可读取：

```python
import machine
print(machine.memory_info())
```

返回 `circle_low_free`、`gc_heap`、`circle_reserve` 和当前 `gc_free` 字节数。

先确认使用镜像 build_id：

```python
from demo.system import board
board.show()
```

下面是此前镜像的 build_id 示例（仅作历史记录）；应将实际输出与所用镜像的构建记录核对，不要求当前构建继续使用此值：

```text
6dd7339465dd0cfaca92a60d797510b3a9676c77548f745c38305b556efff28c
```

先进行 ML/文件媒体 smoke：

```python
from demo.ai import media
print(media.infer('/hello_world_float.tflite', 0.0))
print(media.infer_callable('/hello_world_float.tflite', 0.25))
print(media.image_tensor('/red.png', '/hello_world_float.tflite'))
print(len(media.stream_wav('/input.wav')))
```

确认模型、图片和 WAV 文件均已由用户复制到 SD；这些操作不写盘、不采集摄像头、不联网。

然后按顺序执行：

```python
from demo.network import lan
lan.run()                         # DHCP；记录 ifconfig 和电脑 ping
lan.use_static('192.168.1.50')    # 先关闭 socket；按实际网络修改四元组
lan.use_dhcp(); lan.run()         # 恢复 DHCP
```

电脑端 UDP：

```text
python mpynn/demo/network/pc_echo.py --protocol udp --mode server --host 0.0.0.0 --port 5005
```

板端：

```python
from demo.network import udp
a = udp.client('<电脑IPv4>')
```

电脑端 TCP：

```text
python mpynn/demo/network/pc_echo.py --protocol tcp --mode server --host 0.0.0.0 --port 5006
```

板端：

```python
from demo.network import tcp
tcp.client('<电脑IPv4>')
```

板端 TCP 服务端：

```python
from demo.network import tcp
tcp.server()
```

电脑端改为：

```text
python mpynn/demo/network/pc_echo.py --protocol tcp --mode client --host <板端IPv4> --port 5006
```

DNS/HTTPS：

```python
import network, socket
network.LAN()
print(socket.getaddrinfo('example.com', 443, socket.AF_INET, socket.SOCK_STREAM))
from demo.network import https
https.run('https://example.com/')
```

默认请求使用 `CERT_NONE`，只证明加密请求路径。完整证书验证须先主动校时、准备受信 CA：

```python
https.sync_time('<你的NTP服务器>')
https.run('https://<你的域名>/', '/ca.pem')
```

补充 socket 语义检查：

```python
from demo.network import options, resolver, tcp
options.run()                 # SO_TYPE/SO_ERROR/BROADCAST/NODELAY/亚毫秒超时
resolver.local()              # None/AI_PASSIVE/NUMERIC flags，不查询DNS
resolver.invalid_endpoints() # 非法IPv4/端口在NIC选择前拒绝
```

非阻塞 TCP（先启动电脑 TCP server）：

```python
import socket, select
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setblocking(False)
try:
    try:
        sock.connect(('电脑IPv4', 5006))
    except OSError as error:
        print('connect:', error)       # 预期 EINPROGRESS/EALREADY
    poller = select.poll()
    poller.register(sock, select.POLLOUT | select.POLLERR | select.POLLHUP)
    events = poller.poll(5000)
    print('poll:', events, 'SO_ERROR:', sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR))
    if events and sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0:
        print('peer:', sock.getpeername(), 'local:', sock.getsockname())
finally:
    sock.close()
```

真实 half-close：重新启动电脑 TCP echo server 后，板端执行 `tcp.half_close('电脑IPv4')`；
记录 SHUT_WR 后 EPIPE、完整回显、peer EOF 和电脑抓包 FIN。测试未执行前不算通过。

验证资源回收：关闭全部 UDP/TCP socket 后执行软重启，再重复收发流程；记录 native
句柄是否耗尽。非阻塞没有数据时 EAGAIN 是正常结果，不应当作资源泄漏。
静态地址/DHCP 切换前必须先关闭应用 socket。

每一步记录串口输出、IP、build_id、错误和是否冷启动。不要把开发目录的
`test_*.py` 当成用户演示。
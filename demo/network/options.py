# SPDX-License-Identifier: MIT
"""from demo.network import options; options.run()

测试类型/错误/广播/NODELAY及独立发送接收超时设置/查询。不绑定/发送报文。
需支持 getsockopt hook 的新固件；旧固件缺少方法会失败，不算通过。
"""


def run():
    import network
    import socket
    import struct
    network.LAN()  # 注册 NIC；不请求/发送任何数据
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        assert udp.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) == socket.SOCK_DGRAM
        assert tcp.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) == socket.SOCK_STREAM
        assert udp.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0
        assert tcp.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0
        assert udp.getsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST) == 0
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        assert udp.getsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST) == 1
        raw = udp.getsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 4)
        assert len(raw) == 4 and struct.unpack('i', raw)[0] == 1
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 0)
        assert udp.getsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST) == 0
        # Preserve historical Circle default: Nagle disabled initially.
        assert tcp.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) == 1
        tcp.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 0)
        assert tcp.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) == 0
        tcp.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        assert tcp.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) == 1
        # A positive sub-millisecond value must not silently become nonblocking.
        tcp.settimeout(0.0001)
        assert 0.00099 <= tcp.gettimeout() <= 0.00101
        tcp.settimeout(0)
        assert tcp.gettimeout() == 0
        tcp.settimeout(None)
        assert tcp.gettimeout() is None
        for sock in (udp, tcp):
            sock.settimeout(2)
            assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO) == 2000
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, 50)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO, struct.pack('ii', 0, 1250))
            assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO) == 50
            assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO) == 2
            assert sock.gettimeout() == 2  # Common timeout was not overwritten.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, 0)
            assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO) == 0
            sock.settimeout(None)  # Resets both direction overrides.
            assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO) == 0
            assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO) == 0
        print('SOCKET_OPTION_QUERY_PASS (no packets sent)')
    finally:
        udp.close()
        tcp.close()


if __name__ == '__main__':
    print(__doc__)

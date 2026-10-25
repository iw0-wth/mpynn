# SPDX-License-Identifier: MIT
"""板端 TCP 回显和电脑 TCP 回显客户端；单连接、有限流量。

板端: from demo.network import tcp; tcp.server()
电脑: from demo.network import tcp; tcp.client('192.168.1.20')
默认端口 5006；客户端使用小块 recv_into，服务端遇 EOF 或达到上限结束。
"""


_MAX_BYTES = 65536


def _lan_ready():
    import network

    interface = network.LAN()
    if not interface.isconnected():
        raise OSError('DHCP not ready; run lan.run() first')
    return interface


def client(host, port=5006, nodelay=None):
    """发送小型二进制 payload，检查 sendall 返回 None 和完整回显。"""
    import socket
    import time

    if not 1 <= port <= 65535:
        raise ValueError('port must be 1..65535')
    _lan_ready()
    endpoint = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][-1]
    payload = b'mpynn TCP echo\x00' + bytes(range(256))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(5)
        if nodelay is not None:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, int(bool(nodelay)))
        sock.connect(endpoint)
        if nodelay is not None:
            assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) == int(bool(nodelay))
        peer = sock.getpeername()
        local = sock.getsockname()
        if peer != endpoint:
            raise RuntimeError('unexpected TCP peer: ' + repr(peer))
        result = sock.sendall(payload)
        if result is not None:
            raise RuntimeError('sendall must return None')
        received = bytearray()
        scratch = bytearray(37)
        started = time.ticks_ms()
        while len(received) < len(payload):
            remaining = 5000 - time.ticks_diff(time.ticks_ms(), started)
            if remaining <= 0:
                raise OSError('TCP echo deadline expired')
            sock.settimeout(remaining / 1000)
            count = sock.recv_into(scratch, min(len(scratch), len(payload) - len(received)))
            if not count:
                raise RuntimeError('premature TCP EOF')
            received.extend(memoryview(scratch)[:count])
        if received != payload:
            raise RuntimeError('TCP payload mismatch')
        print('TCP echo verified; peer:', peer, 'local:', local)
    finally:
        sock.close()
    print('TCP_CLIENT_PASS')


def connect_nonblocking(host, port=5006, timeout_ms=5000):
    """只验证非阻塞握手：poll后读取SO_ERROR，再查询peer；不发送echo数据。"""
    import socket
    import select
    import errno
    import time
    if not 1 <= port <= 65535 or timeout_ms <= 0:
        raise ValueError('invalid port or timeout_ms')
    _lan_ready()
    endpoint = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][-1]
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    poller = select.poll()
    registered = False
    try:
        sock.setblocking(False)
        try:
            sock.connect(endpoint)
        except OSError as exc:
            if not exc.args or exc.args[0] not in (errno.EINPROGRESS, errno.EALREADY, errno.EAGAIN):
                raise
        poller.register(sock, select.POLLOUT)
        registered = True
        started = time.ticks_ms()
        while True:
            remaining = timeout_ms - time.ticks_diff(time.ticks_ms(), started)
            if remaining <= 0:
                raise OSError(errno.ETIMEDOUT)
            events = poller.poll(remaining)
            if not events:
                continue
            if any(flags & select.POLLNVAL for _, flags in events):
                raise OSError(errno.EBADF)
            error = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if error:
                raise OSError(error)
            if any(flags & (select.POLLERR | select.POLLHUP) for _, flags in events):
                raise OSError(errno.ENOTCONN)
            if sock.getpeername() != endpoint:
                raise RuntimeError('unexpected peer')
            print('TCP_NONBLOCK_CONNECT_OK:', sock.getsockname(), endpoint)
            return
    finally:
        try:
            if registered:
                poller.unregister(sock)
        finally:
            sock.close()


def half_close(host, port=5006, timeout_ms=5000):
    """发送payload后SHUT_WR，再读完整回显和EOF；与电脑TCP echo server配套。"""
    import socket
    import errno
    import time
    if not 1 <= port <= 65535 or timeout_ms <= 0:
        raise ValueError('invalid port or timeout_ms')
    _lan_ready()
    endpoint = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][-1]
    payload = b'mpynn half-close\x00' + bytes(range(256))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout_ms / 1000)
        sock.connect(endpoint)
        sock.sendall(payload)
        assert sock.shutdown(socket.SHUT_WR) is None
        assert sock.shutdown(socket.SHUT_WR) is None
        try:
            sock.send(b'forbidden')
        except OSError as error:
            if not error.args or error.args[0] != errno.EPIPE:
                raise
        else:
            raise AssertionError('write still allowed after SHUT_WR')
        received = bytearray()
        started = time.ticks_ms()
        while True:
            remaining = timeout_ms - time.ticks_diff(time.ticks_ms(), started)
            if remaining <= 0:
                raise OSError(errno.ETIMEDOUT)
            sock.settimeout(remaining / 1000)
            # Read one extra byte to detect excess echo before EOF.
            data = sock.recv(min(37, len(payload) + 1 - len(received)))
            if not data:
                break
            received.extend(data)
            if len(received) > len(payload):
                raise RuntimeError('excess TCP echo')
        if received != payload:
            raise RuntimeError('half-close TCP payload mismatch')
        print('TCP_HALF_CLOSE_PASS:', sock.getpeername(), len(received), 'bytes and EOF')
    finally:
        sock.close()


def server(port=5006):
    """单连接echo；port=None不显式bind，port=0显式bind临时端口，默认5006。"""
    import socket

    _lan_ready()
    if port is not None and not 0 <= port <= 65535:
        raise ValueError('port must be None or 0..65535')
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.settimeout(30)
        if port is not None:
            listener.bind(('0.0.0.0', port))
        listener.listen(1)
        local = listener.getsockname()
        print('TCP echo listening:', local, '(PC must use assigned port)')
        client, peer = listener.accept()
        try:
            client.settimeout(5)
            total = 0
            while total < _MAX_BYTES:
                data = client.recv(min(1024, _MAX_BYTES - total))
                if not data:
                    print('Peer EOF:', peer, 'echoed:', total)
                    break
                result = client.sendall(data)
                if result is not None:
                    raise RuntimeError('sendall must return None')
                total += len(data)
            print('TCP server finished:', total, 'bytes')
        finally:
            client.close()
    finally:
        listener.close()


if __name__ == '__main__':
    print(__doc__)

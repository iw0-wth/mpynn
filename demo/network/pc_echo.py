# SPDX-License-Identifier: MIT
"""电脑端单连接 UDP/TCP echo 对端，可与板端 demo 配合使用。

启动服务器: python pc_echo.py --protocol udp --mode server --host 0.0.0.0
板端客户端: python pc_echo.py --protocol tcp --mode server --host 0.0.0.0
客户端: python pc_echo.py --protocol udp --mode client --host 192.168.1.20
默认端口 UDP 5005、TCP 5006；仅处理三个 UDP 包或一个 TCP 客户端。
"""


def run(protocol, mode, host, port=None):
    """运行有限时长、单客户端的 UDP/TCP echo server 或 client。"""
    import socket

    if protocol not in ('udp', 'tcp'):
        raise ValueError("protocol must be 'udp' or 'tcp'")
    if mode not in ('server', 'client'):
        raise ValueError("mode must be 'server' or 'client'")
    if port is None:
        port = 5005 if protocol == 'udp' else 5006
    if not 1 <= port <= 65535:
        raise ValueError('port must be 1..65535')

    if protocol == 'udp':
        peer = (host, port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(5 if mode == 'client' else 15)
            if mode == 'server':
                sock.bind(('0.0.0.0' if host == '0.0.0.0' else host, port))
                print('UDP echo listening on', sock.getsockname())
                for index in range(3):
                    data, sender = sock.recvfrom(1472)
                    if sock.sendto(data, sender) != len(data):
                        raise RuntimeError('partial UDP send')
                    print('UDP echoed', index + 1, len(data), 'bytes to', sender)
            else:
                for payload in (b'PC UDP echo', bytes(range(256)), b''):
                    if sock.sendto(payload, peer) != len(payload):
                        raise RuntimeError('partial UDP send')
                    data, sender = sock.recvfrom(2048)
                    if sender != peer or data != payload:
                        raise RuntimeError('wrong UDP peer or payload mismatch')
                    print('UDP verified', len(data), 'bytes from', sender)
        finally:
            sock.close()
        return

    if mode == 'server':
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.settimeout(30)
            listener.bind((host, port))
            listener.listen(1)
            print('TCP echo listening on', listener.getsockname())
            client, sender = listener.accept()
            try:
                client.settimeout(5)
                total = 0
                while total < 65536:
                    data = client.recv(min(1024, 65536 - total))
                    if not data:
                        print('TCP peer EOF:', sender, 'bytes:', total)
                        break
                    client.sendall(data)
                    total += len(data)
                print('TCP server finished:', total, 'bytes')
            finally:
                client.close()
        finally:
            listener.close()
        return

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(5)
        sock.connect((host, port))
        payload = b'mpynn TCP echo\x00' + bytes(range(256))
        if sock.sendall(payload) is not None:
            raise RuntimeError('sendall must return None')
        received = bytearray()
        while len(received) < len(payload):
            part = sock.recv(min(257, len(payload) - len(received)))
            if not part:
                raise RuntimeError('premature TCP EOF')
            received.extend(part)
        if received != payload:
            raise RuntimeError('TCP payload mismatch')
        print('TCP echo verified; peer:', sock.getpeername(), 'local:', sock.getsockname())
    finally:
        sock.close()


def main(argv=None):
    """Parse CLI options and run a selected bounded echo mode."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', required=True, choices=('udp', 'tcp'))
    parser.add_argument('--mode', required=True, choices=('server', 'client'))
    parser.add_argument('--host', required=True, help='bind address or peer IPv4/hostname')
    parser.add_argument('--port', type=int, default=None)
    args = parser.parse_args(argv)
    run(args.protocol, args.mode, args.host, args.port)


if __name__ == '__main__':
    main()

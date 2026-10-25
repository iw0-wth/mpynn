# SPDX-License-Identifier: MIT
"""板端 UDP 回显和电脑 UDP 回显客户端；每次运行都有明确上限。

板端: from demo.network import udp; udp.server()
电脑: from demo.network import udp; udp.client('192.168.1.20')
默认端口 5005；客户端验证文本、二进制和空数据报。
"""


def _lan_ready():
    import network

    interface = network.LAN()
    if not interface.isconnected():
        raise OSError('DHCP not ready; run lan.run() first')
    return interface


def client(host, port=5005):
    """发送三种数据报并验证回显的对端地址和完整 payload。"""
    import socket

    if not 1 <= port <= 65535:
        raise ValueError('port must be 1..65535')
    _lan_ready()
    peer = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)[0][-1]
    payloads = (b'mpynn UDP echo', bytes(range(256)), b'')
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(5)
        for payload in payloads:
            sent = sock.sendto(payload, peer)
            if sent != len(payload):
                raise RuntimeError('partial UDP send')
            received, sender = sock.recvfrom(2048)
            if sender != peer or received != payload:
                raise RuntimeError('wrong UDP peer or payload mismatch')
            print('Echo verified:', len(payload), 'bytes from', sender)
    finally:
        sock.close()
    print('UDP_ECHO_PASS')


def server(port=5005, packets=3):
    """回显有限个数据报（包括空数据报），15 秒无数据即失败。"""
    import socket

    _lan_ready()
    if not 1 <= port <= 65535:
        raise ValueError('port must be 1..65535')
    if packets <= 0:
        raise ValueError('packets must be positive')
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(15)
        sock.bind(('0.0.0.0', port))
        print('UDP echo listening on port', port)
        for index in range(packets):
            data, peer = sock.recvfrom(1472)
            sent = sock.sendto(data, peer)
            if sent != len(data):
                raise RuntimeError('partial UDP echo')
            print('Echoed packet', index + 1, ':', len(data), 'bytes to', peer)
    finally:
        sock.close()
    print('UDP_SERVER_DONE')


if __name__ == '__main__':
    print(__doc__)

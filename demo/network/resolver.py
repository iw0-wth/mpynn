# SPDX-License-Identifier: MIT
"""from demo.network import resolver; resolver.local()

local()只验证地址/标志/服务名，不查询DNS。resolve(host)显式联网查IPv4 A。
"""


def local():
    import socket
    passive = socket.getaddrinfo(None, 5006, socket.AF_INET,
                                 socket.SOCK_STREAM, 0, socket.AI_PASSIVE)
    assert passive[0][-1] == ('0.0.0.0', 5006)
    default = socket.getaddrinfo(None, 80, socket.AF_INET, socket.SOCK_STREAM)
    assert default[0][-1] == ('127.0.0.1', 80)
    # This checks resolver output, not Circle loopback routing support.
    flags = socket.AI_NUMERICHOST | socket.AI_NUMERICSERV
    numeric = socket.getaddrinfo('192.0.2.7', '443', socket.AF_INET,
                                 socket.SOCK_STREAM, 0, flags)
    assert numeric[0][-1] == ('192.0.2.7', 443)
    no_service = socket.getaddrinfo('192.0.2.7', None, socket.AF_INET,
                                    socket.SOCK_DGRAM, 0, flags)
    assert no_service[0][-1] == ('192.0.2.7', 0)
    # Ordinary resolution must also reject malformed digits/dots, not truncate.
    for host in ('256.0.0.1', '1..2.3', '192.0.2.7.8'):
        try:
            socket.getaddrinfo(host, 80, socket.AF_INET, socket.SOCK_STREAM)
        except OSError as error:
            if not error.args or error.args[0] != 22:
                raise
        else:
            raise AssertionError('malformed numeric host accepted')
    print('RESOLVER_LOCAL_FLAGS_OK (no DNS query)')


def invalid_endpoints():
    """验证非法endpoint在NIC选择前被拒绝；不注册网卡、不联网、不写盘。"""
    import socket
    invalid = (('256.0.0.1', 80), ('192.0.2.7suffix', 80),
               ('1..2.3', 80), ('192.0.2.7', -1), ('192.0.2.7', 65536))
    for address in invalid:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for operation in (lambda: sock.bind(address),
                              lambda: sock.connect(address),
                              lambda: sock.sendto(b'never sent', address)):
                try:
                    operation()
                except ValueError:
                    continue
                raise AssertionError('invalid endpoint was not rejected')
        finally:
            sock.close()
    print('INVALID_ENDPOINTS_REJECTED (no NIC or packets)')


def resolve(host, service='https'):
    import network
    import socket
    interface = network.LAN()
    if not interface.isconnected():
        raise OSError('LAN not ready')
    addresses = socket.getaddrinfo(host, service, socket.AF_INET)
    print('Resolved IPv4:', addresses)
    return addresses


if __name__ == '__main__':
    print(__doc__)

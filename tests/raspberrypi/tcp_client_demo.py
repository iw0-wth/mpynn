# SPDX-License-Identifier: MIT
"""Board TCP echo client, numeric IPv4. Requires a PC TCP echo server."""
import network
import socket


def run(host, port=5006, local_port=None):
    lan = network.LAN()
    if not lan.isconnected():
        raise OSError('DHCP not ready')
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.settimeout(5)
        if local_port is not None:
            client.bind(('0.0.0.0', local_port))
        client.connect((host, port))
        assert client.getpeername() == (host, port)
        if local_port:
            assert client.getsockname()[1] == local_port
        payload = b'mpynn TCP echo\x00' + bytes(range(256)) * 8
        offset = 0
        while offset < len(payload):
            count = client.send(memoryview(payload)[offset:])
            if count <= 0:
                raise RuntimeError('send made no progress')
            offset += count
        received = bytearray()
        scratch = bytearray(37)
        while len(received) < len(payload):
            count = client.recv_into(scratch, min(len(scratch), len(payload) - len(received)))
            if not count:
                raise RuntimeError('premature EOF')
            received.extend(memoryview(scratch)[:count])
        assert received == payload
        print('MPYNN_TCP_CLIENT_ECHO_PASS')
    finally:
        client.close()

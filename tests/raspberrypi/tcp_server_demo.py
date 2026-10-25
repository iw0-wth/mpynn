# SPDX-License-Identifier: MIT
"""Board TCP echo server. One client, bounded reads, numeric IPv4 LAN only."""
import network
import socket


def run(port=5006):
    lan = network.LAN()
    if not lan.isconnected():
        raise OSError('DHCP not ready')
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.settimeout(30)
        listener.bind(('0.0.0.0', port))
        listener.listen(2)
        assert listener.getsockname() == ('0.0.0.0', port)
        print('TCP echo at', lan.ifconfig()[0], port)
        client, peer = listener.accept()
        try:
            client.settimeout(5)
            total = 0
            while total < 65536:
                data = client.recv(min(257, 65536 - total))
                if not data:
                    print('Peer EOF', peer, 'echoed', total)
                    break
                offset = 0
                while offset < len(data):
                    count = client.send(memoryview(data)[offset:])
                    if count <= 0:
                        raise RuntimeError('send made no progress')
                    offset += count
                total += len(data)
        finally:
            client.close()
    finally:
        listener.close()

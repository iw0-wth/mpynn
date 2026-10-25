# SPDX-License-Identifier: MIT
"""Board DNS acceptance, once the DNS callback is enabled. Sends a DNS query."""
import network
import socket


def run(host):
    lan = network.LAN()
    if not lan.isconnected():
        raise OSError('DHCP not ready')
    records = socket.getaddrinfo(host, 80, socket.AF_INET, socket.SOCK_STREAM)
    assert records
    for family, kind, protocol, canonname, address in records:
        assert family == socket.AF_INET
        assert kind == socket.SOCK_STREAM and protocol == 6
        assert len(address) == 2 and address[1] == 80
        print(host, '->', address[0])
    print('MPYNN_DNS_LOOKUP_PASS')

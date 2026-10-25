# SPDX-License-Identifier: MIT
"""Run on a PC: python udp_echo_client.py BOARD_IPV4 --port 5005

Start udp_echo_demo.run() on the board first. Sends three bounded datagrams,
requires exact binary echoes from that board/port. No broadcast or SD writes.
"""
import argparse
import ipaddress
import socket


def run(host, port=5005):
    address = str(ipaddress.IPv4Address(host))
    if not 1 <= port <= 65535:
        raise ValueError('port must be 1..65535')
    payloads = [b'mpynn UDP echo', bytes(range(256)), bytes(range(256))*5 + b'end']
    peer = (address, port)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(5)
        for payload in payloads:
            if client.sendto(payload, peer) != len(payload):
                raise RuntimeError('partial UDP send')
            received, sender = client.recvfrom(2048)
            if sender != peer or received != payload:
                raise RuntimeError('wrong peer or payload mismatch')
            print('Echo verified:', len(payload), 'bytes')
    print('UDP_ECHO_ROUNDTRIP_PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host', help='numeric IPv4 shown by board DHCP demo')
    parser.add_argument('--port', type=int, default=5005)
    args = parser.parse_args()
    run(args.host, args.port)

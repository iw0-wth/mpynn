# SPDX-License-Identifier: MIT
# Board-side finite UDP echo responder. Trusted LAN only; no file writes.
# Register network.LAN before creating sockets. Numeric IPv4 only at this stage.
import network
import socket


def run(port=5005, packets=3):
    lan = network.LAN()
    if not lan.isconnected():
        raise OSError('Wait for DHCP using ethernet_demo first')
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        server.settimeout(15)
        server.bind(('0.0.0.0', port))
        print('UDP echo at', lan.ifconfig()[0], port)
        for _ in range(packets):
            data, peer = server.recvfrom(1472)
            # Empty data with a peer is a real zero-payload datagram, not EOF.
            count = server.sendto(data, peer)
            assert count == len(data)
            print('Echoed', count, 'bytes to', peer)
    finally:
        server.close()


if __name__ == '__main__':
    run()

# SPDX-License-Identifier: MIT
"""Public socket contract: LAN registration must precede UDP socket creation."""
import network
import socket
import errno

lan = network.LAN()
assert lan.active()
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.settimeout(0)
    sock.bind(('0.0.0.0', 0))
    try:
        sock.recvfrom(64)
    except OSError as exc:
        if not exc.args or exc.args[0] != errno.EAGAIN:
            raise
    else:
        raise AssertionError('unexpected datagram; repeat on an idle test port')
finally:
    sock.close()
print('MPYNN_NETWORK_SOCKET_CONTRACT_PASS')

# SPDX-License-Identifier: MIT
"""Board TLS client with explicit CA and hostname verification.

Set machine.RTC().datetime(...) to correct UTC first. Supply PEM/DER CA bytes,
not a filename. This demo connects to the provided host and sends an HTTP GET.
"""
import network
import socket
import ssl


def run(host, ca, port=443):
    lan = network.LAN()
    if not lan.isconnected():
        raise OSError('DHCP not ready')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cadata=ca)
    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    secure = None
    try:
        raw.settimeout(10)
        address = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][-1]
        raw.connect(address)
        secure = context.wrap_socket(raw, server_hostname=host)
        request = b'GET / HTTP/1.0\r\nHost: ' + host.encode() + b'\r\n\r\n'
        offset = 0
        while offset < len(request):
            count = secure.write(memoryview(request)[offset:])
            if not count:
                raise RuntimeError('TLS write made no progress')
            offset += count
        print(secure.read(256))
        print('MPYNN_TLS_VERIFIED_HANDSHAKE_PASS')
    finally:
        if secure is not None:
            secure.close()
        else:
            raw.close()

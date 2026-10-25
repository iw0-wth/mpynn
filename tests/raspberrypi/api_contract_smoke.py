# SPDX-License-Identifier: MIT
"""Board-side public API contract; no physical writes or network packets."""
import machine
import network
import socket
import errno

# Boot SD is internal root storage, not a removable MCU-style peripheral.
assert not hasattr(machine, 'SDCard')
assert hasattr(machine, 'RTC')
rtc = machine.RTC()
assert rtc is machine.RTC(0)
date = rtc.datetime()
assert len(date) == 8 and 1970 <= date[0] <= 2038
assert 1 <= date[1] <= 12 and 1 <= date[2] <= 31
# A readable boot clock does not establish externally calibrated UTC.

lan = network.LAN()
assert lan.active() in (True, False)
assert isinstance(lan.ifconfig(), tuple)
assert len(lan.ifconfig()) == 4

# Public UDP subset only. TCP/DNS/TLS are deliberately not claimed here.
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.settimeout(0)
    s.bind(('0.0.0.0', 0))
    assert hasattr(s, 'sendto') and hasattr(s, 'recvfrom')
    try:
        s.recvfrom(32)
    except OSError as exc:
        if not exc.args or exc.args[0] != errno.EAGAIN:
            raise
    else:
        raise AssertionError('unexpected datagram; repeat on an idle test port')
finally:
    s.close()

print('MPYNN_PUBLIC_API_CONTRACT_PASS')

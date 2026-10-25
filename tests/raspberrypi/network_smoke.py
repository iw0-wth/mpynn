# SPDX-License-Identifier: MIT
# On-board diagnostic script; not a Python socket implementation/test.
# Connect onboard RJ45 to a trusted DHCP-enabled LAN before running.
import machine
import network
import time

lan = network.LAN()
assert lan.active()
initial = machine.network_info()
assert lan.ifconfig() == initial['ifconfig']
print('Initial Ethernet state:', initial)
assert isinstance(initial['present'], bool)
assert isinstance(initial['initialized'], bool)
assert len(initial['ifconfig']) == 4
if not initial['present']:
    print('NO_ETHERNET_DEVICE: inspect machine.logs(), USB power and board revision')
else:
    assert len(initial['mac']) == 6
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < 20000:
        state = machine.network_info()
        if state['isconnected']:
            print('MPYNN_DHCP_READY', state)
            break
        time.sleep_ms(100)
    else:
        print('DHCP_NOT_READY (not a PASS):', machine.network_info())

# Reading logs is explicit: background DHCP messages must not corrupt raw REPL.
for _ in range(16):
    chunk = machine.logs()
    if not chunk:
        break
    print(chunk)

# Repeat after Ctrl-D. Confirm the VM resets while network state survives.
# Separately test Thonny raw REPL during DHCP negotiation and cable unplug/replug.
# USB device hotplug, TCP/UDP, DNS and Python sockets are not claimed here.

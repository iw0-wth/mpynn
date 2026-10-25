# SPDX-License-Identifier: MIT
"""Pi 1B onboard RJ45 demo: DHCP + diagnostic output + ping observation.

Run on the board via REPL, or save as /ethernet_demo.py and import it.
No SD writes, external hosts or socket/TLS claims. Use a trusted LAN.
"""
import machine
import network
import time


def logs():
    for _ in range(16):
        chunk = machine.logs()
        if not chunk:
            break
        print(chunk)


def run(timeout_ms=30000, observe_ms=15000):
    lan = network.LAN()
    print('Board:', machine.board_info())
    print('LAN initialized:', lan.active())
    if not lan.active():
        logs()
        raise OSError('LAN initialization failed; inspect USB/LAN9512 logs')
    start = time.ticks_ms()
    while not lan.isconnected():
        if time.ticks_diff(time.ticks_ms(), start) >= timeout_ms:
            print('DHCP timeout:', machine.network_info())
            logs()
            raise OSError('No DHCP lease/link; this is NOT a successful test')
        time.sleep_ms(100)
    ip, mask, gateway, dns = lan.ifconfig()
    print('IPv4:', ip, 'mask:', mask, 'gateway:', gateway, 'DNS:', dns)
    print('State:', machine.network_info())
    print('On another computer on this LAN run: ping', ip)
    print('Keeping cooperative networking alive for', observe_ms, 'ms')
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < observe_ms:
        if not lan.isconnected():
            raise OSError('Ethernet connection lost during observation')
        time.sleep_ms(100)
    print('DHCP/link checks finished. Confirm ping replies on the computer.')
    print('This demo does not verify TCP/UDP sockets, DNS resolution or TLS.')
    return lan.ifconfig()


if __name__ == '__main__':
    run()

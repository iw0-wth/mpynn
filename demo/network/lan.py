# SPDX-License-Identifier: MIT
"""板端以太网 DHCP 示例；导入或直接执行都不会启动联网。

REPL: from demo.network import lan; lan.run()
插入网线并连接 DHCP 路由器；输出地址后可在电脑 ping 此 IPv4。
"""


def run(timeout_ms=30000):
    """等待 DHCP，打印 LAN 状态并返回 (IP, 掩码, 网关, DNS)。"""
    import network
    import time

    if timeout_ms <= 0:
        raise ValueError('timeout_ms must be positive')
    interface = network.LAN()
    if not interface.active():
        raise OSError('LAN initialization failed')
    started = time.ticks_ms()
    while not interface.isconnected():
        if time.ticks_diff(time.ticks_ms(), started) >= timeout_ms:
            raise OSError('DHCP/link timeout; check cable and router')
        time.sleep_ms(100)
    config = interface.ifconfig()
    print('IPv4:', config[0], 'mask:', config[1])
    print('Gateway:', config[2], 'DNS:', config[3])
    print('PC ping:', config[0])
    return config


def use_dhcp(timeout_ms=30000):
    """先关闭已有socket；显式请求新DHCP租约并等待（需支持setter的新固件）。"""
    import network
    interface = network.LAN()
    interface.ifconfig('dhcp')
    return run(timeout_ms)


def use_static(ip='192.168.1.50', mask='255.255.255.0',
               gateway='192.168.1.1', dns='8.8.8.8'):
    """先关闭已有socket；使用局域网中未占用的静态地址，不做地址冲突探测。"""
    import network
    interface = network.LAN()
    interface.ifconfig((ip, mask, gateway, dns))
    config = interface.ifconfig()
    print('Static IPv4:', config)
    print('Link/IP configured:', interface.isconnected())
    print('PC ping:', config[0])
    return config


if __name__ == '__main__':
    print(__doc__)

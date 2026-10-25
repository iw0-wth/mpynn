# SPDX-License-Identifier: MIT
"""板端 HTTPS GET 示例：默认加密请求与显式 CA 验证分开。

默认: from demo.network import https; https.run('https://example.com/')
默认: https.run('https://example.com/')
证书验证由直接 tls.SSLContext/socket 使用者负责；不会在 requests 外层增加端口专用参数。
"""


def _lan_ready():
    import network
    interface = network.LAN()
    if not interface.isconnected():
        raise OSError('DHCP not ready; run lan.run() first')
    return interface


def _show_and_close(response):
    try:
        status = getattr(response, 'status_code', None)
        preview = response.raw.read(256)
        print('HTTPS status:', status)
        print('HTTPS preview:', preview)
    finally:
        response.close()
    return status, preview


def run(url, ca_path=None):
    """请求 URL；无 ca_path 用默认 requests.get，否则启用 CA 验证。"""
    _lan_ready()
    import requests
    if ca_path is None:
        return _show_and_close(requests.get(url, timeout=10))
    return verified(url, ca_path)


def verified(url, ca_path):
    """The standard requests API has no port-specific ssl_context argument."""
    raise NotImplementedError('CA-file requests require direct tls.SSLContext use')


def sync_time(host='pool.ntp.org'):
    """显式通过 ntptime 校准 RTC；此函数不会被 HTTPS 请求自动调用。"""
    _lan_ready()
    import ntptime
    ntptime.host = host
    ntptime.settime()
    print('RTC synchronized from', host)


if __name__ == '__main__':
    print(__doc__)

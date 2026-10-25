# SPDX-License-Identifier: MIT
"""from demo.system import language; language.run()  (语法/冻结库检查，不联网、不写盘)。"""


def run():
    from string.templatelib import Template, Interpolation
    value = 7
    assert f'value={value:03d}' == 'value=007'
    template = t'value={value:03d}'
    assert isinstance(template, Template)
    item = template.interpolations[0]
    assert isinstance(item, Interpolation)
    assert template.strings == ('value=', '')
    assert (item.value, item.expression, item.format_spec) == (7, 'value', '03d')
    assert (1 << 100) >> 100 == 1
    import requests
    import ntptime
    import ssl
    import tls
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    assert context.verify_mode == ssl.CERT_NONE
    assert callable(context.wrap_socket) and callable(tls.SSLContext)
    import bisect
    import functools
    import itertools
    import contextlib
    from collections import defaultdict
    assert callable(requests.get) and callable(ntptime.settime)
    items = [1, 3]
    bisect.insort(items, 2)
    assert items == [1, 2, 3]
    assert functools.partial(pow, 2)(3) == 8
    assert list(itertools.islice(itertools.count(10), 3)) == [10, 11, 12]
    counts = defaultdict(int)
    counts['demo'] += 1
    assert counts['demo'] == 1

    @contextlib.contextmanager
    def example():
        yield 42

    with example() as result:
        assert result == 42
    print('LANGUAGE_FROZEN_LIBRARIES_OK')


if __name__ == '__main__':
    print(__doc__)

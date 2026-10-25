# SPDX-License-Identifier: MIT
"""User-facing board network demos; importing performs no network IO."""
from . import lan, udp, tcp, https, options, resolver

__all__ = ('lan', 'udp', 'tcp', 'https', 'options', 'resolver')

# SPDX-License-Identifier: MIT
"""Run on the board to exercise enabled runtime syntax, not just mpy-cross."""
from string.templatelib import Template, Interpolation

value = 7
assert f'value={value:03d}' == 'value=007'
template = t'value={value:03d}'
assert isinstance(template, Template)
assert template.strings == ('value=', '')
item = template.interpolations[0]
assert isinstance(item, Interpolation)
assert item.value == 7
assert item.expression == 'value'
assert item.format_spec == '03d'
assert [x * x for x in range(4)] == [0, 1, 4, 9]
assert (1 << 100) >> 100 == 1
print('MPYNN_SYNTAX_SMOKE_PASS')

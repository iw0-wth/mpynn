"""Run on packed-profile firmware, with the common acceptance module on SD."""
from vc4_multitile_acceptance_1024x2048 import run
run(require_counters=True, require_packed=True)

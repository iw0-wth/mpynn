# mpynn local Git baseline

The initial local baseline is commit `a09eaca47e44fd73f976a64d4d5cc31581208dde`
on `main`. The publication remote is `https://gitee.com/wth_iw0/mpynn`; subsequent
cleanup, documentation and demo changes are recorded as separate commits.
Existing local source files were preserved; submodule HEAD/index setup did not
checkout/reset source trees. Build products and Python test caches are excluded.
The original baseline is a snapshot, not a fabricated reconstruction of earlier
unrecorded implementation steps.

## Dependency gitlinks

The parent commit records Git submodule pointers, not vendored copies of these
repositories. Paths retain the OpenMV layout, including `lib/tflm/libtflm`.

| Path | Remote | Pinned commit |
| --- | --- | --- |
| lib/tinyusb | https://gitee.com/wth_iw0/tinyusb | aa0fc2e08f1c2dd6f026a431e8989357fbb4c5bf |
| lib/micropython | https://gitee.com/wth_iw0/micropython | 0fd6c573ea815774668bbb16b8e197c8822368b2 |
| modules/ulab | https://gitee.com/wth_iw0/micropython-ulab | d161443327173bcf94c2616cb5de37e290af71ca |
| lib/tflm/libtflm | https://gitee.com/wth_iw0/libtflm-mpynn | 9008e63d0acb5a3c739a46af85636e837c6835b2 |
| lib/vc4-runtime | https://gitee.com/wth_iw0/vc4-runtime | 92faccf96be7edb65ddfe2138192e0ac2d6f793f |
| lib/circle | https://gitee.com/wth_iw0/circle | 7a81e1b480fe7d19fc1fc695b89bff0a0848f44b |
| lib/apriltag | https://github.com/openmv/apriltag.git | 636b9ba14ba8485c9fc09590cd4ef53f11427966 |
| tools/alif | https://github.com/micropython/alif-security-toolkit.git | 63698efe8567eed115fe620d5e5de75f460310d7 |
| scripts/libraries/microdot | https://github.com/miguelgrinberg/microdot.git | b241dfce270883e5018f0b8ec8f5821ea4fe156e |

The three unchanged OpenMV pointers and original ulab/tinyusb versions were
verified against original OpenMV commit
`222310c96500a7f6d63a37ae90e02db8dbbe35f7`, identified by its source ZIP comment.
All 4,488 original ZIP blobs match that commit's recursive Git tree. AprilTag,
alif and microdot remain uninitialized empty directories locally.

## Local development state

Circle HEAD is fixed at the requested `7a81e1b`. Two pre-existing local source
changes (an SDHOST transfer-error check and a blank line in a network header)
are preserved as working-tree differences, not silently committed into that
upstream or substituted with another parent pin. A parent commit stores the pin,
not these local edits.

MicroPython's manually copied nested dependencies are intentionally left alone;
the parent pin is exactly the requested commit. `git status` can report the
MicroPython submodule as modified due to those development copies. No nested
repository content was staged into this parent baseline.

The local ulab directory is the existing 70-file source subset at the pinned
revision plus `VENDOR.json` / `MPYNN_INTEGRATION.md`. The 70 upstream files match
that commit's blob hashes. Missing upstream ancillary files and the two local
records can make its working tree appear modified. They were preserved rather
than replaced with a full checkout. That local state does not change its parent
gitlink; do not blindly reset it to make the display clean.

## External tests and user demos

The initial baseline included `tests/`. The later source-layout cleanup moved
that entire project test tree to workspace `tests/`, beside this repository.
Raspberry Pi smoke/benchmark/fixture Python utilities moved there as well.
The mpynn Git diff therefore shows removal of the old in-repository test paths;
their current source is preserved outside this repository, not deleted from the
workspace. Previous overlapping sibling variants were archived under
`build/test-migration-backup/previous-sibling-tests/` before merging.

User examples are maintained in `demo/`, independently of development tests.
Normal firmware builds do not need the external tests: `check-config` uses its
port-owned `ports/raspberrypi/config_checks.c`. The independent VC4 runtime's own
submodule tests are outside the scope of this main-project move.

## Routine commands

```sh
git status --short
git diff
git diff --cached
git add <intended-project-files>
git commit -m "Describe the change"

# View parent-only changes while leaving nested development copies alone:
git status --short --ignore-submodules=dirty
```

On a fresh clone, initialize only dependencies required for the target first:

```sh
git submodule update --init lib/tinyusb lib/micropython modules/ulab \
  lib/tflm/libtflm lib/vc4-runtime lib/circle
```

Nested MicroPython libraries are a separate development setup; this baseline did
not recursively reinitialize them. Parent Git history records only submodule
commits, so new changes inside a dependency must be committed/published in that
repository before updating its parent gitlink. No `ignore=all` settings are used
to conceal pointer changes.

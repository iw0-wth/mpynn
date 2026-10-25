# SPDX-License-Identifier: MIT
"""Compile real SPI C++ bridge and real GPIO registry against strict Circle doubles.

No hardware claims: validates ownership before construction, rollback, context,
bounded calls, manual CS, overlap handling and status mapping. C binding is ARM
compiled separately; surface assertions keep hardware and upstream SoftSPI registrations separate.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from test_pin_policy import GPIO_STUB

PORT = Path(__file__).resolve().parents[2] / 'ports/raspberrypi'
MACHINE = r'''
#ifndef TEST_MACHINE_H
#define TEST_MACHINE_H
enum TMachineModel { MachineModelBRelease1MB256, MachineModelBRelease2MB256,
    MachineModelBRelease2MB512, MachineModelUnknown };
extern TMachineModel test_model;
extern unsigned core_clock;
enum { CLOCK_ID_CORE = 4 };
class CMachineInfo {
public:
    static CMachineInfo *Get() { static CMachineInfo value; return &value; }
    TMachineModel GetMachineModel() { return test_model; }
    unsigned GetClockRate(unsigned id) { assert(id == CLOCK_ID_CORE); return core_clock; }
};
#endif
'''
SPI = r'''
#ifndef TEST_SPI_H
#define TEST_SPI_H
#include <cassert>
#include <cstdint>
#include "gpio_bridge.h"
extern bool initialize_ok;
extern unsigned constructions, destructions, set_clocks, set_modes, transfers;
extern int transfer_result;
extern const unsigned char other_owner;
enum { SPI_MASTER_TIMEOUT = 1, SPI_MASTER_INVALID_ARGUMENT = 2 };
class CSPIMaster {
public:
    const unsigned ChipSelectNone = 3;
    CSPIMaster(unsigned baud, unsigned pol, unsigned phase, unsigned device) {
        assert(baud >= 4000 && baud <= 125000000 && pol <= 1 && phase <= 1 && device == 0);
        // Strict double checks the REAL registry, not a mock claim function.
        // Every constructor-configured pin must already be exclusively owned.
        for (int pin=7; pin<=11; ++pin) assert(mpynn_gpio_claim(pin, &other_owner) == MPYNN_GPIO_BUSY);
        ++constructions;
    }
    ~CSPIMaster() {
        for (int pin=7; pin<=11; ++pin) assert(mpynn_gpio_claim(pin, &other_owner) == MPYNN_GPIO_BUSY);
        ++destructions;
    }
    bool Initialize() { return initialize_ok; }
    void SetClock(unsigned baud) { assert(baud >= 4000 && baud <= 125000000); ++set_clocks; }
    void SetMode(unsigned pol, unsigned phase) { assert(pol <= 1 && phase <= 1); ++set_modes; }
    int WriteRead(unsigned cs, const void *src, void *dest, unsigned count) {
        assert(cs == ChipSelectNone && count && count <= 65535 && (src || dest));
        ++transfers;
        if (transfer_result < 0) return transfer_result;
        auto input = static_cast<const uint8_t *>(src);
        auto output = static_cast<uint8_t *>(dest);
        // byte-wise exchange supports exact in-place buffers.
        for (unsigned i=0; i<count; ++i) {
            uint8_t value = input ? input[i] : 0;
            if (output) output[i] = value ^ 0x55;
        }
        return transfer_result ? transfer_result : static_cast<int>(count);
    }
};
#endif
'''
HARNESS = r'''
#include <circle/gpiopin.h>
#include <circle/machineinfo.h>
#include <circle/spimaster.h>
#include "machine_spi.h"
#include "gpio_bridge.h"
#include <cstdio>
std::vector<Event> events;
u32 pad_levels;
TMachineModel test_model = MachineModelBRelease2MB512;
unsigned core_clock = 250000000;
unsigned level;
bool initialize_ok = true;
unsigned constructions, destructions, set_clocks, set_modes, transfers;
int transfer_result;
const unsigned char other_owner = 0;
unsigned CurrentExecutionLevel() { return level; }
static void reclaim_every_pad() {
    for (int pin=7; pin<=11; ++pin) assert(mpynn_gpio_claim(pin, &other_owner) == 0);
    mpynn_gpio_release_all(&other_owner);
}
int main() {
    // Atomic failure at EACH possible pin: no partial claims/no MMIO.
    for (int conflict=7; conflict<=11; ++conflict) {
        assert(mpynn_gpio_claim(conflict, &other_owner) == 0);
        events.clear();
        assert(mpynn_spi_init(1000000,0,0) == MPYNN_SPI_BUSY);
        assert(constructions == 0 && events.empty());
        reclaim_every_pad();
    }
    // claim_many preflight must preserve existing same-owner claims too.
    const unsigned char atomic_owner = 0;
    int invalid[] = {7, 8, 54};
    assert(mpynn_gpio_claim_many(invalid, 3, &atomic_owner) == MPYNN_GPIO_INVALID);
    assert(mpynn_gpio_claim_many(nullptr, 3, &other_owner) == MPYNN_GPIO_INVALID);
    assert(mpynn_gpio_claim_many(invalid, 0, &other_owner) == MPYNN_GPIO_INVALID);
    assert(mpynn_gpio_claim_many(invalid, 3, nullptr) == MPYNN_GPIO_INVALID);
    reclaim_every_pad();
    test_model = MachineModelUnknown;
    assert(mpynn_spi_init(1000000,0,0) == MPYNN_SPI_BOARD);
    assert(constructions == 0);
    test_model = MachineModelBRelease2MB512;
    core_clock = 0;
    assert(mpynn_spi_init(1000000,0,0) == MPYNN_SPI_IO);
    assert(constructions == 0);
    core_clock = 250000000;
    assert(mpynn_spi_init(0,0,0) == MPYNN_SPI_INVALID);
    assert(mpynn_spi_init(3999,0,0) == MPYNN_SPI_INVALID);
    assert(mpynn_spi_init(125000001,0,0) == MPYNN_SPI_INVALID);
    assert(mpynn_spi_init(1000000,2,0) == MPYNN_SPI_INVALID);
    assert(mpynn_spi_init(1000000,0,2) == MPYNN_SPI_INVALID);
    for (level=1; level<=2; ++level) {
        assert(mpynn_spi_init(1000000,0,0) == MPYNN_SPI_BUSY);
        assert(mpynn_spi_check() == MPYNN_SPI_BUSY);
        assert(mpynn_spi_deinit() == MPYNN_SPI_BUSY);
        assert(mpynn_spi_transfer(0,nullptr,nullptr) == MPYNN_SPI_BUSY);
    }
    level=0;
    assert(mpynn_spi_check() == MPYNN_SPI_UNINITIALIZED);
    assert(mpynn_spi_transfer(0,nullptr,nullptr) == MPYNN_SPI_UNINITIALIZED);
    initialize_ok = false;
    assert(mpynn_spi_init(1000000,0,0) == MPYNN_SPI_IO);
    assert(constructions == 1 && destructions == 1);
    reclaim_every_pad();
    initialize_ok = true;
    assert(mpynn_spi_init(1000000,0,0) == 0);
    assert(constructions == 2 && destructions == 1);
    assert(mpynn_spi_init(2000000,1,1) == 0);
    assert(constructions == 2 && set_clocks == 1 && set_modes == 1);
    assert(mpynn_spi_init(1000000,3,0) == MPYNN_SPI_INVALID);
    assert(set_modes == 1);
    unsigned char data[] = {1,2,3,4}, dest[4] = {};
    assert(mpynn_spi_transfer(0,nullptr,nullptr) == 0);
    assert(mpynn_spi_transfer(65536,data,dest) == MPYNN_SPI_INVALID);
    assert(mpynn_spi_transfer(1,nullptr,nullptr) == MPYNN_SPI_INVALID);
    assert(mpynn_spi_transfer(3,data,data+1) == MPYNN_SPI_INVALID);
    assert(mpynn_spi_transfer(3,data+1,data) == MPYNN_SPI_INVALID);
    assert(transfers == 0);
    assert(mpynn_spi_transfer(4,data,dest) == 0);
    assert(dest[0] == (1^0x55) && dest[3] == (4^0x55));
    assert(mpynn_spi_transfer(4,data,data) == 0);
    assert(data[0] == (1^0x55));
    assert(mpynn_spi_transfer(4,data,nullptr) == 0);
    assert(mpynn_spi_transfer(4,nullptr,dest) == 0 && dest[0] == 0x55);
    transfer_result = -SPI_MASTER_TIMEOUT;
    assert(mpynn_spi_transfer(4,data,dest) == MPYNN_SPI_TIMEOUT);
    transfer_result = -SPI_MASTER_INVALID_ARGUMENT;
    assert(mpynn_spi_transfer(4,data,dest) == MPYNN_SPI_INVALID);
    transfer_result = 3; // short transfer must not count as success
    assert(mpynn_spi_transfer(4,data,dest) == MPYNN_SPI_IO);
    level=1;
    unsigned calls=transfers;
    assert(mpynn_spi_transfer(4,data,dest) == MPYNN_SPI_BUSY);
    assert(mpynn_spi_init(1000000,0,0) == MPYNN_SPI_BUSY);
    assert(mpynn_spi_deinit() == MPYNN_SPI_BUSY);
    assert(transfers == calls && destructions == 1);
    level=0;
    assert(mpynn_spi_deinit() == 0 && destructions == 2);
    assert(mpynn_spi_deinit() == 0 && destructions == 2);
    reclaim_every_pad();
    assert(mpynn_spi_check() == MPYNN_SPI_UNINITIALIZED);
    std::puts("PASS");
}
'''


class MachineSPIHostTests(unittest.TestCase):
    def test_strict_doubles_real_spi_bridge_and_gpio_registry(self):
        cxx = (os.environ.get('CXX') or
               ('E:/msys64/ucrt64/bin/g++.exe' if Path('E:/msys64/ucrt64/bin/g++.exe').is_file() else None) or
               shutil.which('g++') or shutil.which('clang++'))
        self.assertTrue(cxx, 'native C++ compiler required')
        env = os.environ.copy()
        # Native MSYS2 compilers/cc1 must find their runtime DLLs.
        env['PATH'] = str(Path(cxx).parent) + os.pathsep + env.get('PATH', '')
        with tempfile.TemporaryDirectory(prefix='machine-spi-host-') as tmp:
            root = Path(tmp)
            circle = root / 'circle'
            circle.mkdir()
            for filename, content in {
                'gpiopin.h': GPIO_STUB, 'machineinfo.h': MACHINE, 'spimaster.h': SPI,
                'synchronize.h': '#define TASK_LEVEL 0\nunsigned CurrentExecutionLevel();\n',
                'new.h': '#include <new>\n',
            }.items():
                (circle / filename).write_text(content, encoding='utf-8')
            source = root / 'spi_test.cpp'
            source.write_text(HARNESS, encoding='utf-8')
            binary = root / ('spi.exe' if os.name == 'nt' else 'spi')
            result = subprocess.run([cxx, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-pedantic',
                '-I', str(root), '-I', str(PORT), str(source), str(PORT / 'machine_spi.cpp'),
                str(PORT / 'gpio_bridge.cpp'), '-o', str(binary)], env=env,
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), 'PASS')

    def test_safe_standard_surface(self):
        config = (PORT / 'mpconfigport.h').read_text(encoding='utf-8')
        source = (PORT / 'machine_spi.c').read_text(encoding='utf-8')
        self.assertIn('#define MICROPY_PY_MACHINE_SPI (1)', config)
        self.assertIn('#define MICROPY_PY_MACHINE_SOFTSPI (1)', config)
        for method in ('init', 'deinit', 'read', 'readinto', 'write', 'write_readinto'):
            self.assertIn('MP_QSTR_' + method, source)
        self.assertIn('MP_ETIMEDOUT', source)
        self.assertIn('MP_EBUSY', source)
        self.assertIn('length < 0', source)
        self.assertIn('len > 0xFFFF', source)
        self.assertIn('buffers must be the same length', source)
        self.assertIn('fixed pins; omit sck/mosi/miso', source)
        makefile = (PORT / 'Makefile').read_text(encoding='utf-8')
        self.assertIn('machine_spi.c', makefile)
        self.assertIn('machine_spi.cpp', makefile)
        self.assertIn('%.bridge.o: %.cpp', makefile)
        self.assertIn('$(CIRCLE_BUILD)/lib/libcircle.a', makefile)
        # Standard extmod registers SPI through the enable flag; there must be
        # no duplicate port registration or accidental SoftSPI extra-global.
        module = (PORT / 'modmachine_port.c').read_text(encoding='utf-8')
        self.assertNotIn('MP_QSTR_SoftSPI', module)
        self.assertNotIn('MP_QSTR_SPI', module)
        main = (PORT / 'mpmain.c').read_text(encoding='utf-8')
        self.assertLess(main.index('(void)mpynn_spi_deinit();'), main.index('mp_deinit();'))

if __name__ == '__main__':
    unittest.main()

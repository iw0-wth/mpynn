# SPDX-License-Identifier: MIT
"""Compile the actual network snapshot bridge against fake Circle state.

Not a packet/DHCP/ARM test; verifies snapshot copying and lifecycle/context guards.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PORT = Path(__file__).resolve().parents[2] / 'ports/raspberrypi'
CXX = Path('E:/msys64/ucrt64/bin/g++.exe')
HEADER = r'''
#pragma once
#include <cstdint>
#include <cstring>
struct CIPAddress {
    uint8_t data[4] = {};
    void CopyTo(uint8_t *out) const { memcpy(out, data, 4); }
};
struct CNetConfig {
    bool dhcp = true;
    CIPAddress ip{{192,168,1,70}}, gateway{{192,168,1,1}}, dns{{192,168,1,2}};
    uint8_t mask[4] = {255,255,255,0};
    bool IsDHCPUsed() const { return dhcp; }
    const CIPAddress *GetIPAddress() const { return &ip; }
    const uint8_t *GetNetMask() const { return mask; }
    const CIPAddress *GetDefaultGateway() const { return &gateway; }
    const CIPAddress *GetDNSServer() const { return &dns; }
};
struct CNetSubSystem {
    bool running = false;
    CNetConfig config;
    mutable unsigned calls = 0;
    bool IsRunning() const { ++calls; return running; }
    CNetConfig *GetConfig() { ++calls; return &config; }
    void Configure(const uint8_t *ip=nullptr, const uint8_t *mask=nullptr,
                   const uint8_t *gateway=nullptr, const uint8_t *dns=nullptr) {
        ++calls;
        config.dhcp = ip == nullptr;
        running = ip != nullptr;
        memset(config.ip.data, 0, 4); memset(config.mask, 0, 4);
        memset(config.gateway.data, 0, 4); memset(config.dns.data, 0, 4);
        if (ip) {
            memcpy(config.ip.data, ip, 4); memcpy(config.mask, mask, 4);
            memcpy(config.gateway.data, gateway, 4); memcpy(config.dns.data, dns, 4);
        }
    }
};
'''
SOURCE = r'''
#include <cassert>
#include <cstring>
#include <circle/net/netsubsystem.h>
#include "network_bridge.h"
unsigned execution_level;
int main() {
    mpynn_network_state_t out, zero = {};
    memset(&out, 0xff, sizeof out);
    assert(mpynn_network_snapshot(nullptr) == -2);
    assert(mpynn_network_snapshot(&out) == 0);
    assert(memcmp(&out, &zero, sizeof out) == 0);
    CNetSubSystem net;
    mpynn_network_attach(&net, 1);
    assert(mpynn_network_snapshot(&out) == 0);
    assert(out.initialized && !out.running && out.dhcp);
    assert(out.ip[0] == 192 && out.ip[3] == 70);
    assert(out.netmask[2] == 255 && out.netmask[3] == 0);
    assert(out.gateway[3] == 1 && out.dns[3] == 2);
    net.running = true;
    net.config.ip.data[3] = 99;
    assert(out.ip[3] == 70); // snapshot is independent of live configuration
    assert(mpynn_network_snapshot(&out) == 0);
    assert(out.running && out.ip[3] == 99);
    for (unsigned level=1; level<=2; ++level) {
        unsigned before = net.calls;
        execution_level = level;
        mpynn_network_attach(nullptr, 0); // must not mutate from masked/IRQ context
        memset(&out, 0x55, sizeof out);
        mpynn_network_state_t expected = out;
        assert(mpynn_network_snapshot(&out) == -3);
        assert(net.calls == before && memcmp(&out, &expected, sizeof out) == 0);
    }
    execution_level = 0;
    assert(mpynn_network_snapshot(&out) == 0 && out.initialized);
    mpynn_network_attach(&net, 0);
    assert(mpynn_network_snapshot(&out) == 0 && !out.initialized);
    assert(memcmp(&out, &zero, sizeof out) == 0);
    mpynn_network_attach(nullptr, 1);
    assert(mpynn_network_snapshot(&out) == 0 && !out.initialized);
    assert(mpynn_network_configure(nullptr) == 19);
    mpynn_network_attach(&net, 1);
    mpynn_network_state_t fixed = {};
    uint8_t ip[] = {10, 20, 30, 40}, mask[] = {255, 255, 255, 0};
    memcpy(fixed.ip, ip, 4); memcpy(fixed.netmask, mask, 4);
    fixed.gateway[0]=10; fixed.gateway[1]=20; fixed.gateway[2]=30; fixed.gateway[3]=1;
    fixed.dns[0]=1; fixed.dns[1]=1; fixed.dns[2]=1; fixed.dns[3]=1;
    execution_level = 1;
    unsigned before = net.calls;
    assert(mpynn_network_configure(&fixed) == 16 && net.calls == before);
    execution_level = 0;
    mpynn_network_state_t invalid = {};
    assert(mpynn_network_configure(&invalid) == 22 && net.calls == before);
    invalid.ip[0] = 224;
    assert(mpynn_network_configure(&invalid) == 22 && net.calls == before);
    invalid = fixed; invalid.netmask[2] = 250;
    assert(mpynn_network_configure(&invalid) == 22 && net.calls == before);
    invalid = fixed; memset(invalid.netmask, 0, 4);
    assert(mpynn_network_configure(&invalid) == 22 && net.calls == before);
    invalid = fixed; invalid.ip[3] = 255;
    assert(mpynn_network_configure(&invalid) == 22 && net.calls == before);
    invalid = fixed; invalid.ip[3] = 0;
    assert(mpynn_network_configure(&invalid) == 22 && net.calls == before);
    invalid = fixed; invalid.gateway[2] = 31;
    assert(mpynn_network_configure(&invalid) == 22 && net.calls == before);
    invalid = fixed; invalid.gateway[3] = 255;
    assert(mpynn_network_configure(&invalid) == 22 && net.calls == before);
    invalid = fixed; invalid.dns[0] = 224;
    assert(mpynn_network_configure(&invalid) == 22 && net.calls == before);
    invalid = fixed; invalid.ip[0] = 127;
    assert(mpynn_network_configure(&invalid) == 22 && net.calls == before);
    assert(mpynn_network_configure(&fixed) == 0);
    memset(&fixed, 0, sizeof fixed); // copied, never retained
    assert(mpynn_network_snapshot(&out) == 0 && !out.dhcp && out.running);
    assert(memcmp(out.ip, ip, 4) == 0 && memcmp(out.netmask, mask, 4) == 0);
    assert(out.gateway[3] == 1 && out.dns[3] == 1);
    assert(mpynn_network_configure(nullptr) == 0);
    assert(mpynn_network_snapshot(&out) == 0 && out.dhcp && !out.running);
    assert(!(out.ip[0] | out.ip[1] | out.ip[2] | out.ip[3]));
}
'''


class NetworkBridgeTests(unittest.TestCase):
    def test_snapshots_lifecycle_and_irq_guards(self):
        if not CXX.is_file():
            self.skipTest('host g++ unavailable')
        env = os.environ.copy()
        env['PATH'] = str(CXX.parent) + os.pathsep + env.get('PATH', '')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'circle/net').mkdir(parents=True)
            (root/'circle/net/netsubsystem.h').write_text(HEADER)
            (root/'circle/synchronize.h').write_text(
                '#pragma once\n#define TASK_LEVEL 0\nextern unsigned execution_level;\n'
                'inline unsigned CurrentExecutionLevel() { return execution_level; }\n')
            (root/'main.cpp').write_text(SOURCE)
            exe = root/'test.exe'
            commands = [
                [str(CXX), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                 '-I'+str(root), '-I'+str(PORT), str(PORT/'network_bridge.cpp'),
                 str(root/'main.cpp'), '-o', str(exe)], [str(exe)]]
            for command in commands:
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, str(command)+'\n'+result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()

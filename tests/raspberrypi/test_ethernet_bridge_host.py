# SPDX-License-Identifier: MIT
"""Link real Ethernet diagnostic bridge with fake Circle device objects."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PORT = Path(__file__).resolve().parents[2] / 'ports/raspberrypi'
CXX = Path('E:/msys64/ucrt64/bin/g++.exe')
HEADERS = {
    'circle/synchronize.h': '#pragma once\n#define TASK_LEVEL 0\nextern unsigned execution_level;\ninline unsigned CurrentExecutionLevel() { return execution_level; }\n',
    'circle/macaddress.h': '''#pragma once
#include <cstdint>
struct CMACAddress {
    uint8_t bytes[6];
    void CopyTo(uint8_t *dst) const { for (int i=0;i<6;i++) dst[i]=bytes[i]; }
};
''',
    'circle/netdevice.h': '''#pragma once
#include <circle/macaddress.h>
enum TNetDeviceType { NetDeviceTypeEthernet, NetDeviceTypeOther };
class CNetDevice {
public:
    static CNetDevice *found;
    static CNetDevice *GetNetDevice(unsigned index) { return index==0 ? found : nullptr; }
    virtual TNetDeviceType GetType() { return NetDeviceTypeEthernet; }
    virtual const CMACAddress *GetMACAddress() const = 0;
    virtual bool IsLinkUp() { return false; }
    virtual int GetLinkSpeed() { return 0; }
};
'''
}
HARNESS = '''#include <cassert>
#include <cstdint>
#include "ethernet_bridge.h"
#include <circle/netdevice.h>
unsigned execution_level;
CNetDevice *CNetDevice::found;
class FakeNet : public CNetDevice {
public:
  CMACAddress mac{{1,2,3,4,5,6}};
  bool have_mac = true, up = false, ethernet = true;
  int speed = 4;
  TNetDeviceType GetType() override { return ethernet ? NetDeviceTypeEthernet : NetDeviceTypeOther; }
  const CMACAddress *GetMACAddress() const override { return have_mac ? &mac : nullptr; }
  bool IsLinkUp() override { return up; }
  int GetLinkSpeed() override { return speed; }
};
int main() {
 uint8_t mac[6] = {}; unsigned link = 55, speed = 66;
 assert(mpynn_eth_snapshot(nullptr, &link, &speed) == -2);
 assert(mpynn_eth_snapshot(mac, nullptr, &speed) == -2);
 assert(mpynn_eth_snapshot(mac, &link, nullptr) == -2);
 assert(mpynn_eth_snapshot(mac, &link, &speed) == -1);
 FakeNet device; CNetDevice::found = &device;
 for (unsigned level = 1; level <= 2; ++level) {
   execution_level = level;
   assert(mpynn_eth_snapshot(mac, &link, &speed) == -3);
   assert(link == 55 && speed == 66 && mac[0] == 0);
 }
 execution_level = 0;
 device.ethernet = false;
 assert(mpynn_eth_snapshot(mac, &link, &speed) == -1);
 device.ethernet = true; device.have_mac = false;
 assert(mpynn_eth_snapshot(mac, &link, &speed) == -1);
 device.have_mac = true;
 assert(mpynn_eth_snapshot(mac, &link, &speed) == 0);
 assert(!link && speed == 4);
 for (int i=0; i<6; i++) assert(mac[i] == i+1);
 device.up = true; device.speed = 3;
 assert(mpynn_eth_snapshot(mac, &link, &speed) == 0);
 assert(link == 1 && speed == 3);
}
'''


class EthernetBridgeTests(unittest.TestCase):
    def test_nic_diagnostics_and_absence(self):
        if not CXX.is_file():
            self.skipTest('host g++ unavailable')
        env = os.environ.copy()
        env['PATH'] = str(CXX.parent) + os.pathsep + env.get('PATH', '')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, text in HEADERS.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding='ascii')
            harness = root / 'main.cpp'
            harness.write_text(HARNESS, encoding='ascii')
            executable = root / 'test.exe'
            for command in ([str(CXX), '-std=c++17', '-Wall', '-Wextra', '-Werror',
                             '-I'+str(root), '-I'+str(PORT), str(PORT/'ethernet_bridge.cpp'),
                             str(harness), '-o', str(executable)], [str(executable)]):
                result = subprocess.run(command, capture_output=True, text=True, timeout=30, env=env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()

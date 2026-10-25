# SPDX-License-Identifier: MIT
"""Run the complete override IsPortInUse method with host-only Circle doubles.

PtrArray, spinlock and connections are fakes; protocol constants come from the
actual Circle header. Only the extracted production method is compiled, without
Circle libraries, build output, firmware, native sockets or a replacement scan.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
CIRCLE = ROOT / "lib/circle"
SOURCE = ROOT / "ports/raspberrypi/upstream_overrides/circle/lib/net/transportlayer.cpp"
CXX = Path("E:/msys64/ucrt64/bin/g++.exe")


def method(source):
    """Extract the whole actual definition, including both lock-release paths."""
    match = re.search(r"\b(?:boolean|bool)\s+CTransportLayer::IsPortInUse\s*\(", source)
    if match is None:
        raise AssertionError("production CTransportLayer::IsPortInUse definition missing")
    start = match.start()
    brace = source.index("{", match.end())
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


FAKE = r"""
#include <cassert>
#include <cstdio>
#include <string>
#include <vector>
#include <circle/net/in.h>
using u16 = unsigned short;
using boolean = bool;
#define TRUE true
#define FALSE false
static_assert(sizeof(u16) == 2);

static bool querying = false;
struct CSpinLock {
    bool held = false;
    unsigned acquires = 0, releases = 0;
    void Acquire() { assert(!held); held = true; ++acquires; }
    void Release() { assert(held); held = false; ++releases; }
};
struct CNetConnection {
    inline static unsigned creations = 0, destructions = 0;
    inline static unsigned port_reads = 0, protocol_reads = 0;
    CSpinLock *lock;
    u16 port;
    int protocol;
    bool terminated, retained;
    CNetConnection(CSpinLock *l, u16 p, int proto, bool closed, bool owned)
        : lock(l), port(p), protocol(proto), terminated(closed), retained(owned) {
        assert(!querying); ++creations;
    }
    ~CNetConnection() { assert(!querying); ++destructions; }
    u16 GetOwnPort() const { assert(lock->held); ++port_reads; return port; }
    int GetProtocol() const { assert(lock->held); ++protocol_reads; return protocol; }
    bool IsTerminated() const { assert(lock->held); return terminated; }
    bool HasOwners() const { assert(lock->held); return retained; }
};
struct CPtrArray {
    CSpinLock *lock;
    std::vector<void *> entries;
    mutable unsigned count_reads = 0;
    unsigned slot_reads = 0, appends = 0, removals = 0;
    explicit CPtrArray(CSpinLock *l) : lock(l) {}
    unsigned GetCount() const {
        assert(lock->held); ++count_reads; return unsigned(entries.size());
    }
    void *&operator[](unsigned index) {
        assert(lock->held && index < entries.size()); ++slot_reads;
        return entries[index];
    }
    unsigned Append(void *entry) {
        assert(!querying); ++appends;
        unsigned index = unsigned(entries.size()); entries.push_back(entry); return index;
    }
    void RemoveLast() { assert(!querying); ++removals; entries.pop_back(); }
};
struct CScheduler {
    inline static unsigned yields = 0;
    static CScheduler *Get() { static CScheduler scheduler; return &scheduler; }
    void Yield() { assert(!querying); ++yields; }
};
struct CTransportLayer {
    CSpinLock m_SpinLock;
    CPtrArray m_pConnection{&m_SpinLock};
    u16 m_nOwnPort = 60421;
    ~CTransportLayer() {
        assert(!m_SpinLock.held && m_SpinLock.acquires == m_SpinLock.releases);
        for (void *entry : m_pConnection.entries) delete static_cast<CNetConnection *>(entry);
    }
    unsigned seed(u16 port, int protocol, bool closed = false, bool retained = false) {
        assert(!querying);
        unsigned index = unsigned(m_pConnection.entries.size());
        m_pConnection.entries.push_back(
            new CNetConnection(&m_SpinLock, port, protocol, closed, retained));
        return index;
    }
    void hole() { assert(!querying); m_pConnection.entries.push_back(nullptr); }
    bool IsPortInUse(u16, int);
};
"""


HARNESS = r"""
struct ConnectionState {
    CNetConnection *pointer;
    u16 port;
    int protocol;
    bool terminated, retained;
};
static void check(CTransportLayer &tr, u16 port, int protocol, bool expected) {
    assert(!querying && !tr.m_SpinLock.held);
    const auto entries = tr.m_pConnection.entries;
    std::vector<ConnectionState> states;
    for (void *entry : entries) {
        auto *connection = static_cast<CNetConnection *>(entry);
        if (connection) states.push_back({connection, connection->port, connection->protocol,
                                         connection->terminated, connection->retained});
    }
    const unsigned acquires = tr.m_SpinLock.acquires, releases = tr.m_SpinLock.releases;
    const unsigned count_reads = tr.m_pConnection.count_reads;
    const unsigned slot_reads = tr.m_pConnection.slot_reads;
    const unsigned port_reads = CNetConnection::port_reads;
    const unsigned protocol_reads = CNetConnection::protocol_reads;
    const unsigned creations = CNetConnection::creations, destructions = CNetConnection::destructions;
    const unsigned yields = CScheduler::yields;
    const unsigned appends = tr.m_pConnection.appends, removals = tr.m_pConnection.removals;
    const u16 cursor = tr.m_nOwnPort;
    querying = true;
    const bool result = tr.IsPortInUse(port, protocol);
    querying = false;
    assert(result == expected && !tr.m_SpinLock.held);
    const unsigned locks = port == 0 ? 0 : 1;
    assert(tr.m_SpinLock.acquires == acquires + locks);
    assert(tr.m_SpinLock.releases == releases + locks);
    assert(tr.m_pConnection.entries == entries && tr.m_nOwnPort == cursor);
    assert(tr.m_pConnection.appends == appends && tr.m_pConnection.removals == removals);
    assert(CNetConnection::creations == creations && CNetConnection::destructions == destructions);
    assert(CScheduler::yields == yields);
    for (const auto &state : states) {
        assert(state.pointer->port == state.port && state.pointer->protocol == state.protocol);
        assert(state.pointer->terminated == state.terminated && state.pointer->retained == state.retained);
    }
    if (port == 0) {
        assert(tr.m_pConnection.count_reads == count_reads && tr.m_pConnection.slot_reads == slot_reads);
        assert(CNetConnection::port_reads == port_reads && CNetConnection::protocol_reads == protocol_reads);
    }
}
int main(int argc, char **argv) {
    assert(argc == 3);
    const std::string scenario = argv[1], protocol_name = argv[2];
    assert(protocol_name == "tcp" || protocol_name == "udp");
    const int protocol = protocol_name == "tcp" ? IPPROTO_TCP : IPPROTO_UDP;
    const int opposite = protocol == IPPROTO_TCP ? IPPROTO_UDP : IPPROTO_TCP;
    CTransportLayer tr;
    if (scenario == "empty") {
        check(tr, 8080, protocol, false);
        check(tr, 65535, protocol, false);
    } else if (scenario == "occupied") {
        tr.seed(8080, protocol);
        check(tr, 8080, protocol, true); // match at index zero must release the lock
        check(tr, 8080, opposite, false); // same port, separate TCP/UDP namespace
        check(tr, 8081, protocol, false); // same protocol, different port
        check(tr, 8080, protocol, true); // repeated calls have no side effects
    } else if (scenario == "holes") {
        tr.hole(); tr.hole(); tr.hole();
        check(tr, 8080, protocol, false);
        tr.seed(8080, opposite);
        tr.hole();
        check(tr, 8080, protocol, false);
        check(tr, 8080, opposite, true);
    } else if (scenario == "late-entry") {
        tr.hole();
        tr.seed(8080, opposite); // port alone is not sufficient
        tr.seed(8081, protocol); // protocol alone is not sufficient
        tr.hole(); tr.hole();
        tr.seed(8080, protocol); // the matching entry is after all the holes
        check(tr, 8080, protocol, true);
        check(tr, 8082, protocol, false);
        check(tr, 8080, opposite, true);
    } else if (scenario == "zero") {
        tr.seed(0, protocol);
        tr.hole();
        tr.seed(0, opposite);
        tr.seed(65535, protocol);
        for (int proto : {protocol, opposite, IPPROTO_ICMP, -1}) check(tr, 0, proto, false);
        // Port zero must also work while the caller already holds the spinlock.
        tr.m_SpinLock.Acquire();
        const unsigned acquires = tr.m_SpinLock.acquires, releases = tr.m_SpinLock.releases;
        querying = true;
        assert(!tr.IsPortInUse(0, protocol));
        querying = false;
        assert(tr.m_SpinLock.held && tr.m_SpinLock.acquires == acquires);
        assert(tr.m_SpinLock.releases == releases);
        tr.m_SpinLock.Release();
    } else if (scenario == "boundary") {
        tr.seed(1, protocol);
        tr.hole();
        tr.seed(65535, protocol);
        check(tr, 1, protocol, true);
        check(tr, 65535, protocol, true);
        check(tr, 65534, protocol, false);
        check(tr, 65535, opposite, false);
        check(tr, 0, protocol, false);
    } else if (scenario == "closed") {
        tr.seed(8080, protocol, true, true); // retained terminal native object
        tr.seed(8081, protocol, true, false); // owner released, Process has not removed it
        check(tr, 8080, protocol, true);
        check(tr, 8081, protocol, true);
        check(tr, 8080, opposite, false);
        check(tr, 8081, opposite, false);
    } else {
        assert(scenario == "removed");
        tr.seed(7070, opposite); // keep the removed slot an internal hole
        unsigned index = tr.seed(8080, protocol, true, true);
        tr.seed(9090, protocol);
        check(tr, 8080, protocol, true);
        auto *closed = static_cast<CNetConnection *>(tr.m_pConnection.entries[index]);
        closed->retained = false;
        check(tr, 8080, protocol, true); // release alone does not make the port free
        // Model actual Process removal: delete the native object and clear its slot.
        delete closed;
        tr.m_pConnection.entries[index] = nullptr;
        check(tr, 8080, protocol, false);
        check(tr, 9090, protocol, true); // removal hole must not stop later lookups
        check(tr, 7070, opposite, true);
        check(tr, 8080, protocol, false);
    }
    puts("PASS");
}
"""


@unittest.skipUnless(CXX.is_file(), "host g++ unavailable")
class PortInUseHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        definition = method(SOURCE.read_text(encoding="utf-8"))
        temporary = tempfile.TemporaryDirectory(prefix="mpynn-port-in-use-")
        def cleanup():
            for attempt in range(21):
                try:
                    temporary.cleanup()
                    return
                except PermissionError:
                    if attempt == 20:
                        raise
                    time.sleep(0.1)
        cls.addClassCleanup(cleanup)
        cls.root = Path(temporary.name)
        harness = cls.root / "test.cpp"
        harness.write_text(FAKE + "\n" + definition + "\n" + HARNESS, encoding="utf-8")
        cls.executable = cls.root / "test.exe"
        cls.env = os.environ.copy()
        cls.env["PATH"] = str(CXX.parent) + os.pathsep + cls.env.get("PATH", "")
        cls.env["TMP"] = cls.env["TEMP"] = cls.env["TMPDIR"] = str(cls.root)
        result = subprocess.run(
            [str(CXX), "-std=c++17", "-Wall", "-Wextra", "-Werror",
             # Circle's bare-metal assert.h must not shadow the host assert.h.
             "-idirafter", str(CIRCLE / "include"), str(harness), "-o", str(cls.executable)],
            cwd=cls.root, env=cls.env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError("host g++ compile failed:\n" + result.stdout + result.stderr)

    def run_scenario(self, scenario):
        for protocol in ("tcp", "udp"):
            with self.subTest(protocol=protocol):
                result = subprocess.run(
                    [str(self.executable), scenario, protocol], cwd=self.root, env=self.env,
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("PASS", result.stdout)

    def test_empty_table_is_available_and_unlocks(self):
        self.run_scenario("empty")

    def test_occupied_port_matches_both_port_and_protocol_and_unlocks(self):
        self.run_scenario("occupied")

    def test_null_holes_are_safe_and_do_not_end_lookup(self):
        self.run_scenario("holes")

    def test_late_matching_entry_after_holes_and_mismatches_is_found(self):
        self.run_scenario("late-entry")

    def test_port_zero_returns_false_without_lock_or_table_reads(self):
        self.run_scenario("zero")

    def test_nonzero_u16_boundaries_including_65535(self):
        self.run_scenario("boundary")

    def test_closed_retained_and_unowned_native_objects_still_occupy_ports(self):
        self.run_scenario("closed")

    def test_only_actual_pointer_removal_makes_port_available(self):
        self.run_scenario("removed")


if __name__ == "__main__":
    unittest.main()

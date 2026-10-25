# SPDX-License-Identifier: MIT
"""Execute the production TCP PacketReceived override against strict host doubles."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "ports/raspberrypi/upstream_overrides/circle/lib/net/tcpconnection.cpp"
CXX = Path("E:/msys64/ucrt64/bin/g++.exe")


def method(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


@contextmanager
def host_temp_directory():
    """Retry Windows executable-lock cleanup finitely, only within our temp root."""
    prefix = "mpynn-tcp-packet-host-"
    root = Path(tempfile.mkdtemp(prefix=prefix)).resolve()
    try:
        yield root
    finally:
        if root.parent != Path(tempfile.gettempdir()).resolve() or not root.name.startswith(prefix):
            raise RuntimeError("refusing cleanup outside this test's temporary directory")
        for attempt in range(5):
            try:
                shutil.rmtree(root)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))


FAKE = r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <deque>
#include <vector>
#include <tuple>
#include <utility>
#include <cstdio>

using u8 = std::uint8_t;
using u16 = std::uint16_t;
using u32 = std::uint32_t;
using boolean = bool;
#define TRUE true
#define FALSE false
#include <circle/net/in.h>
#include <circle/net/error.h>
#define CHECKSUM_OK 0
#define TCP_MAX_CONNECTIONS 32
#define TCP_CONFIG_RX_THRESHOLD 65535
#define TCP_CONFIG_WINDOW 65535
#define TCP_MAX_WINDOW 65535
#define MAX_RETRANSMISSIONS 5
#define HZ_FIN_TIMEOUT 100
#define HZ_TIMEWAIT 200
#define NEW_STATE(state) (m_State = state)
#define UNEXPECTED_STATE() UnexpectedState(__LINE__)
#define FLIGHT_SIZE (m_nSND_NXT - m_nSND_UNA)
#define min(a,b) ((a) < (b) ? (a) : (b))
#define max(a,b) ((a) > (b) ? (a) : (b))
// The production packed header and flag/offset definitions are inserted here.
/* PRODUCTION_TCP_HEADER */

enum TTCPState {
  TCPStateClosed, TCPStateListen, TCPStateSynSent, TCPStateSynReceived,
  TCPStateEstablished, TCPStateFinWait1, TCPStateFinWait2, TCPStateCloseWait,
  TCPStateClosing, TCPStateLastAck, TCPStateTimeWait
};
enum TTCPTimer { TCPTimerUser, TCPTimerRetransmission, TCPTimerTimeWait, TCPTimerUnknown };

static u16 be2le16(u16 value) { return static_cast<u16>((value >> 8) | (value << 8)); }
static u32 be2le32(u32 value) {
  return ((value >> 24) & 0xffu) | ((value >> 8) & 0xff00u)
       | ((value << 8) & 0xff0000u) | ((value << 24) & 0xff000000u);
}
static bool lt(u32 a, u32 b) { return static_cast<std::int32_t>(a - b) < 0; }
static bool le(u32 a, u32 b) { return static_cast<std::int32_t>(a - b) <= 0; }
static bool gt(u32 a, u32 b) { return lt(b, a); }
static bool ge(u32 a, u32 b) { return le(b, a); }
static bool bwl(u32 a, u32 b, u32 c) { return le(a, b) && lt(b, c); }
static bool bwh(u32 a, u32 b, u32 c) { return lt(a, b) && le(b, c); }
static bool bwlh(u32 a, u32 b, u32 c) { return le(a, b) && le(b, c); }

static_assert(sizeof(TTCPHeader) == 20, "production TCP base header is packed and 20 bytes");
static_assert(offsetof(TTCPHeader, nDataOffsetFlags) == 12, "production flags offset");
static_assert(offsetof(TTCPHeader, nWindow) == 14, "production window offset");

class CIPAddress {
public:
  CIPAddress() : address(0) {}
  explicit CIPAddress(u32 value) : address(value) {}
  void Set(u32 value) { address = value; }
  void Set(const CIPAddress &other) { address = other.address; }
  CIPAddress &operator=(u32 value) { address = value; return *this; }
  bool operator==(const CIPAddress &other) const { return address == other.address; }
  bool operator!=(const CIPAddress &other) const { return !(*this == other); }
  bool IsMulticast() const { return (address & 0xf0000000u) == 0xe0000000u; }
  bool IsBroadcast() const { return address == 0xffffffffu; }
  u32 Value() const { return address; }
private:
  u32 address;
};

class CNetConfig {
public:
  CNetConfig() : ip(0), broadcast(0xffffffffu) {}
  const CIPAddress *GetIPAddress() const { return &ip; }
  const CIPAddress *GetBroadcastAddress() const { return &broadcast; }
  void SetIPAddress(u32 value) { ip.Set(value); }
  void SetBroadcast(u32 value) { broadcast.Set(value); }
private:
  CIPAddress ip;
  CIPAddress broadcast;
};

class CNetBuffer {
public:
  static unsigned destroyed;
  static unsigned alive;
  explicit CNetBuffer(std::size_t length = 0) : bytes(length), head(0), private_data(0) { ++alive; }
  CNetBuffer(const CNetBuffer &) = delete;
  CNetBuffer &operator=(const CNetBuffer &) = delete;
  ~CNetBuffer() { ++destroyed; assert(alive > 0); --alive; }
  void *GetPtr() const { return const_cast<u8 *>(bytes.data() + head); }
  std::size_t GetLength() const { return bytes.size() - head; }
  void *RemoveHeader(std::size_t length) { assert(length <= GetLength()); head += length; return GetPtr(); }
  void SetPrivateData(const void *data, std::size_t length) {
    assert(length <= sizeof(private_bytes));
    std::memcpy(private_bytes, data, length);
    private_data = length;
  }
  const void *GetPrivateData() const { return private_data ? private_bytes : nullptr; }
  const u8 *Raw() const { return bytes.data(); }
private:
  std::vector<u8> bytes;
  std::size_t head;
  u8 private_bytes[20]{};
  std::size_t private_data;
};
unsigned CNetBuffer::destroyed = 0;
unsigned CNetBuffer::alive = 0;

class Queue {
public:
  ~Queue() { Flush(); }
  bool IsEmpty() const { return packets.empty(); }
  unsigned GetBytesQueued() const {
    unsigned total = 0;
    for (const CNetBuffer *packet : packets) total += static_cast<unsigned>(packet->GetLength());
    return total;
  }
  void Enqueue(CNetBuffer *packet) { assert(packet != nullptr); ++enqueue_calls; packets.push_back(packet); }
  unsigned enqueue_calls = 0;
  CNetBuffer *Dequeue() {
    if (packets.empty()) return nullptr;
    CNetBuffer *packet = packets.front(); packets.pop_front(); return packet;
  }
  void Flush(std::size_t bytes = static_cast<std::size_t>(-1)) {
    while (!packets.empty() && bytes > 0) {
      CNetBuffer *packet = packets.front();
      if (bytes != static_cast<std::size_t>(-1) && packet->GetLength() > bytes) break;
      packets.pop_front();
      if (bytes != static_cast<std::size_t>(-1)) bytes -= packet->GetLength();
      delete packet;
    }
  }
  std::size_t Size() const { return packets.size(); }
private:
  std::deque<CNetBuffer *> packets;
};

class Reassembly {
public:
  explicit Reassembly(Queue *rx) : rx_queue(rx) {}
  ~Reassembly() { Flush(); }
  bool Enqueue(u32 sequence, CNetBuffer *packet) {
    ++enqueue_calls;
    assert(packet != nullptr);
    pending.emplace_back(sequence, packet);
    return true;
  }
  u32 Dequeue(u32 next) {
    ++dequeue_calls;
    for (auto it = pending.begin(); it != pending.end();) {
      if (it->first == next) {
        next += static_cast<u32>(it->second->GetLength());
        rx_queue->Enqueue(it->second);
        it = pending.erase(it);
        it = pending.begin();
      } else {
        ++it;
      }
    }
    return next;
  }
  void Flush() { for (const auto &entry : pending) delete entry.second; pending.clear(); }
  std::size_t Size() const { return pending.size(); }
  unsigned enqueue_calls = 0;
  unsigned dequeue_calls = 0;
private:
  Queue *rx_queue;
  std::vector<std::pair<u32, CNetBuffer *>> pending;
};

class Event {
public:
  void Set() { ++sets; }
  unsigned sets = 0;
};
class Timer {
public:
  unsigned GetTicks() const { return 1; }
};
class RTO {
public:
  unsigned GetRTO() const { return 100; }
  void SegmentSent(u32, unsigned = 0) {}
  void SegmentAcknowledged(u32) {}
  void Initialize(u32, u32, u16) {}
};
class Checksum {
public:
  void SetDestinationAddress(const CIPAddress &) { ++destination_sets; }
  unsigned Calculate(const void *, std::size_t) { ++calculations; return CHECKSUM_OK; }
  unsigned destination_sets = 0;
  unsigned calculations = 0;
};
class SpinLock {
public:
  void Acquire() {}
  void Release() {}
};

struct CTCPConnection {
  static unsigned s_nConnections;
  TTCPState m_State = TCPStateEstablished;
  TTCPState m_StateAfterFIN = TCPStateFinWait1;
  int m_nErrno = 0;
  bool m_bActiveOpen = true;
  bool m_bNoDelay = true;
  bool m_bRetransmit = false;
  bool m_bSendSYN = false;
  bool m_bFINQueued = false;
  bool m_bFINSent = false;
  bool m_bFINReceived = false;
  bool m_bTimedOut = false;
  bool m_bFastRecovery = false;
  bool m_bReadShutdown = false;
  bool m_bWriteShutdown = false;
  unsigned m_nRetransmissionCount = 0;
  unsigned m_nReceiveTimeout = 0;
  unsigned m_nSendTimeout = 0;
  unsigned m_nOwnPort = 4000;
  unsigned m_nForeignPort = 5000;
  CIPAddress m_ForeignIP = CIPAddress(0x0a000002u);
  CIPAddress m_ReceiverIP = CIPAddress(0x0a000001u);
  Checksum m_Checksum;
  Queue m_TxQueue;
  Queue m_RxQueue;
  Reassembly m_ReassemblyQueue{&m_RxQueue};
  Event m_Event;
  Event m_TxEvent;
  Timer m_Timer;
  Timer *m_pTimer = &m_Timer;
  RTO m_RTOCalculator;
  SpinLock m_TimerSpinLock;
  u32 m_nSND_UNA = 500;
  u32 m_nSND_NXT = 500;
  u32 m_nSND_WND = 4096;
  u16 m_nSND_UP = 0;
  u32 m_nSND_WL1 = 0;
  u32 m_nSND_WL2 = 0;
  u32 m_nISS = 499;
  u32 m_nRCV_NXT = 1000;
  u32 m_nRCV_WND = 4096;
  u32 m_nIRS = 999;
  u16 m_nSND_MSS = 536, m_nMSS = 536;
  u32 m_nIW = 2144;
  u32 m_nCWND = 4096;
  u32 m_nSSThresh = 65535;
  unsigned m_nDupAckCount = 0;
  u32 m_nRecover = 0;
  unsigned m_nLastSendTicks = 0;
  unsigned sends = 0;
  unsigned lastFlags = 0;
  u32 lastSequence = 0;
  u32 lastAcknowledgment = 0;
  void StopTimer(unsigned) {}
  void StartTimer(unsigned, unsigned) {}
  void ResendSegment() {}
  void OnDuplicateAck() { ++m_nDupAckCount; }
  u32 CalculateISN() { return 123; }
  boolean ScanOptions(TTCPHeader *);
  void UnexpectedState(unsigned) { assert(false && "unexpected TCP state"); }
  auto Snapshot() const {
    return std::make_tuple(m_State, m_StateAfterFIN, m_nErrno,
      m_bActiveOpen, m_bNoDelay, m_bRetransmit, m_bSendSYN, m_bFINQueued,
      m_bFINSent, m_bFINReceived, m_bTimedOut, m_bFastRecovery,
      m_bReadShutdown, m_bWriteShutdown, m_nRetransmissionCount,
      m_nOwnPort, m_nForeignPort, m_ForeignIP.Value(),
      m_nSND_UNA, m_nSND_NXT, m_nSND_WND, m_nSND_UP, m_nSND_WL1,
      m_nSND_WL2, m_nISS, m_nRCV_NXT, m_nRCV_WND, m_nIRS,
      m_nSND_MSS, m_nIW, m_nCWND, m_nSSThresh, m_nDupAckCount,
      m_nRecover, m_nLastSendTicks, m_Event.sets, m_TxEvent.sets,
      m_Checksum.calculations, m_Checksum.destination_sets,
      m_TxQueue.Size(), m_TxQueue.GetBytesQueued(), m_TxQueue.enqueue_calls,
      m_RxQueue.Size(), m_RxQueue.GetBytesQueued(), m_RxQueue.enqueue_calls, m_ReassemblyQueue.Size(),
      m_ReassemblyQueue.enqueue_calls, m_ReassemblyQueue.dequeue_calls,
      sends, lastFlags, lastSequence, lastAcknowledgment);
  }
  bool SendSegment(unsigned flags, u32 sequence, u32 acknowledgment = 0, CNetBuffer *packet = nullptr) {
    ++sends;
    lastFlags = flags;
    lastSequence = sequence;
    lastAcknowledgment = acknowledgment;
    delete packet;
    return true;
  }
  int PacketReceived(CNetBuffer *, CIPAddress &, CIPAddress &, int);
};
unsigned CTCPConnection::s_nConnections = 0;
'''


HARNESS = r'''
static CNetBuffer *packet(u32 sequence, u32 acknowledgment, unsigned flags,
                          unsigned length, unsigned dest_port = 4000,
                          unsigned source_port = 5000) {
  const unsigned header_length = sizeof(TTCPHeader);
  CNetBuffer *result = new CNetBuffer(header_length + length);
  TTCPHeader *header = static_cast<TTCPHeader *>(result->GetPtr());
  std::memset(header, 0, sizeof(*header));
  header->nSourcePort = be2le16(static_cast<u16>(source_port));
  header->nDestPort = be2le16(static_cast<u16>(dest_port));
  header->nSequenceNumber = be2le32(sequence);
  header->nAcknowledgmentNumber = be2le32(acknowledgment);
  header->nDataOffsetFlags = static_cast<u16>((header_length / 4) << TCP_DATA_OFFSET_SHIFT) | static_cast<u16>(flags);
  header->nWindow = be2le16(4096);
  for (unsigned i = 0; i < length; ++i) static_cast<u8 *>(result->GetPtr())[header_length + i] = static_cast<u8>(i + 1);
  return result;
}

static void endpoint(CIPAddress &sender, CIPAddress &receiver) {
  sender.Set(0x0a000002u);
  receiver.Set(0x0a000001u);
}

int main() {
  CIPAddress sender;
  CIPAddress receiver;
  endpoint(sender, receiver);
  assert(sender == CIPAddress(0x0a000002u));
  assert(!sender.IsMulticast() && !sender.IsBroadcast());
  CIPAddress multicast(0xe0000001u);
  CIPAddress broadcast(0xffffffffu);
  assert(multicast.IsMulticast() && broadcast.IsBroadcast());
  CNetConfig config;
  config.SetIPAddress(0x0a000001u);
  config.SetBroadcast(0x0a0000ffu);
  assert(*config.GetIPAddress() == receiver);
  assert(config.GetBroadcastAddress()->IsBroadcast() == false);

  // In-order data is delivered when reads remain enabled, and ACK advances RCV.NXT.
  CTCPConnection delivered;
  const unsigned destroyed_before_delivered = CNetBuffer::destroyed;
  CNetBuffer *in_order = packet(1000, 500, TCP_FLAG_ACK | TCP_FLAG_PUSH, 4);
  assert(delivered.PacketReceived(in_order, sender, receiver, IPPROTO_TCP) == 1);
  assert(delivered.m_nRCV_NXT == 1004);
  assert(delivered.m_RxQueue.Size() == 1 && delivered.m_RxQueue.GetBytesQueued() == 4);
  assert(delivered.m_ReassemblyQueue.dequeue_calls == 1);
  assert(delivered.sends == 1 && delivered.lastFlags == TCP_FLAG_ACK);
  assert(delivered.lastSequence == 500 && delivered.lastAcknowledgment == 1004);
  assert(delivered.m_State == TCPStateEstablished && !delivered.m_bFINReceived);
  assert(CNetBuffer::destroyed == destroyed_before_delivered);

  // Read shutdown consumes payload while preserving TCP sequence progress.
  CTCPConnection discarded;
  discarded.m_bReadShutdown = true;
  const unsigned destroyed_before_discard = CNetBuffer::destroyed;
  assert(discarded.PacketReceived(packet(1000, 500, TCP_FLAG_ACK | TCP_FLAG_PUSH, 4), sender, receiver, IPPROTO_TCP) == 1);
  assert(discarded.m_nRCV_NXT == 1004);
  assert(discarded.m_RxQueue.IsEmpty() && discarded.m_RxQueue.enqueue_calls == 0);
  assert(discarded.m_ReassemblyQueue.dequeue_calls == 1);
  assert(discarded.sends == 1 && discarded.lastFlags == TCP_FLAG_ACK);
  assert(discarded.lastSequence == 500 && discarded.lastAcknowledgment == 1004);
  assert(discarded.m_State == TCPStateEstablished && !discarded.m_bFINReceived);
  assert(CNetBuffer::destroyed == destroyed_before_discard + 1);

  // A data-plus-FIN segment under read shutdown is consumed without RX enqueue.
  CTCPConnection fin;
  fin.m_bReadShutdown = true;
  const unsigned destroyed_before_fin = CNetBuffer::destroyed;
  assert(fin.PacketReceived(packet(1000, 500, TCP_FLAG_ACK | TCP_FLAG_PUSH | TCP_FLAG_FIN, 4), sender, receiver, IPPROTO_TCP) == 1);
  assert(fin.m_nRCV_NXT == 1005);
  assert(fin.m_bFINReceived && fin.m_State == TCPStateCloseWait);
  assert(fin.m_RxQueue.IsEmpty() && fin.m_RxQueue.enqueue_calls == 0);
  assert(fin.sends == 2 && fin.lastAcknowledgment == 1005);
  assert(CNetBuffer::destroyed == destroyed_before_fin + 1);

  // Out-of-order discarded data is ACKed and never enters reassembly.
  CTCPConnection out_of_order;
  out_of_order.m_bReadShutdown = true;
  const unsigned destroyed_before_ooo = CNetBuffer::destroyed;
  assert(out_of_order.PacketReceived(packet(1007, 500, TCP_FLAG_ACK | TCP_FLAG_PUSH, 3), sender, receiver, IPPROTO_TCP) == 1);
  assert(out_of_order.m_nRCV_NXT == 1000);
  assert(out_of_order.m_RxQueue.IsEmpty());
  assert(out_of_order.m_ReassemblyQueue.enqueue_calls == 0 && out_of_order.m_ReassemblyQueue.Size() == 0);
  assert(out_of_order.m_RxQueue.enqueue_calls == 0);
  assert(out_of_order.sends == 1 && out_of_order.lastFlags == TCP_FLAG_ACK);
  assert(out_of_order.lastSequence == 500 && out_of_order.lastAcknowledgment == 1000);
  assert(CNetBuffer::destroyed == destroyed_before_ooo + 1);

  // Early rejection leaves ownership with the caller and mutates no connection state.
  CTCPConnection rejected;
  const auto rejected_snapshot = rejected.Snapshot();
  for (bool wrong_protocol : {true, false}) {
    CNetBuffer *not_mine = packet(1000, 500, TCP_FLAG_ACK | TCP_FLAG_PUSH, 4, wrong_protocol ? 4000 : 4001);
    const unsigned tag = 0x12345678u;
    not_mine->SetPrivateData(&tag, sizeof(tag));
    void *const original_head = not_mine->GetPtr();
    const std::size_t original_length = not_mine->GetLength();
    const auto *bytes = static_cast<const u8 *>(original_head);
    const std::vector<u8> original_bytes(bytes, bytes + original_length);
    const unsigned before_rejection = CNetBuffer::destroyed;
    assert(rejected.PacketReceived(not_mine, sender, receiver, wrong_protocol ? IPPROTO_UDP : IPPROTO_TCP) == 0);
    assert(rejected.Snapshot() == rejected_snapshot);
    assert(CNetBuffer::destroyed == before_rejection);
    assert(not_mine->GetPtr() == original_head && not_mine->GetLength() == original_length);
    assert(std::memcmp(not_mine->GetPtr(), original_bytes.data(), original_length) == 0);
    assert(std::memcmp(not_mine->GetPrivateData(), &tag, sizeof(tag)) == 0);
    assert(sender == CIPAddress(0x0a000002u) && receiver == CIPAddress(0x0a000001u));
    delete not_mine;  // A zero return retains ownership with the caller.
    assert(CNetBuffer::destroyed == before_rejection + 1);
  }
  // Malformed TCP header is instead consumed by the connection with -1.
  const unsigned before_invalid = CNetBuffer::destroyed;
  assert(rejected.PacketReceived(new CNetBuffer(sizeof(TTCPHeader) - 1), sender, receiver, IPPROTO_TCP) == -1);
  assert(CNetBuffer::destroyed == before_invalid + 1 && rejected.Snapshot() == rejected_snapshot);

  // Invalid data offsets are consumed before RemoveHeader/subtraction/options.
  for(unsigned offset : {0u,1u,4u,6u,15u}) {
    CTCPConnection malformed;
    CNetBuffer *p=packet(1000,500,TCP_FLAG_ACK,0);
    auto *h=static_cast<TTCPHeader *>(p->GetPtr());
    h->nDataOffsetFlags=static_cast<u16>(offset<<TCP_DATA_OFFSET_SHIFT)|TCP_FLAG_ACK;
    const unsigned freed=CNetBuffer::destroyed;
    assert(malformed.PacketReceived(p,sender,receiver,IPPROTO_TCP)==-1);
    assert(CNetBuffer::destroyed==freed+1 && !malformed.sends);
    assert(malformed.m_nRCV_NXT==1000 && malformed.m_RxQueue.IsEmpty());
  }
  // Correct extent but malformed zero-length TLV cannot hang or partially set MSS.
  for(unsigned kind : {2u,30u}) {
    CTCPConnection malformed;
    CNetBuffer *p=packet(1000,500,TCP_FLAG_ACK,4);
    auto *h=static_cast<TTCPHeader *>(p->GetPtr());
    h->nDataOffsetFlags=static_cast<u16>(6<<TCP_DATA_OFFSET_SHIFT)|TCP_FLAG_ACK;
    auto *options=static_cast<u8 *>(p->GetPtr())+sizeof(TTCPHeader);
    options[0]=static_cast<u8>(kind); options[1]=0;
    assert(malformed.PacketReceived(p,sender,receiver,IPPROTO_TCP)==-1);
    assert(malformed.m_nSND_MSS==536 && malformed.m_nCWND==4096 && !malformed.sends);
  }

  // Read shutdown remains effective while our native write FIN is in flight.
  for (TTCPState state : {TCPStateFinWait1, TCPStateFinWait2}) {
    CTCPConnection halfclosed;
    halfclosed.m_State = state;
    halfclosed.m_bReadShutdown = true;
    halfclosed.m_bWriteShutdown = true;
    halfclosed.m_bFINSent = true;
    halfclosed.m_nSND_UNA = 500;
    halfclosed.m_nSND_NXT = 501;
    assert(halfclosed.PacketReceived(packet(1000, 501, TCP_FLAG_ACK | TCP_FLAG_PUSH | TCP_FLAG_FIN, 4), sender, receiver, IPPROTO_TCP) == 1);
    assert(halfclosed.m_State == TCPStateTimeWait && halfclosed.m_bFINReceived);
    assert(halfclosed.m_nRCV_NXT == 1005 && halfclosed.m_RxQueue.IsEmpty());
    assert(halfclosed.lastFlags == TCP_FLAG_ACK && halfclosed.lastAcknowledgment == 1005);
  }
  // Peer FIN racing a locally queued (not yet sent) FIN changes the post-FIN state.
  CTCPConnection queued_fin;
  queued_fin.m_bReadShutdown = true;
  queued_fin.m_bWriteShutdown = true;
  queued_fin.m_bFINQueued = true;
  assert(queued_fin.PacketReceived(packet(1000, 500, TCP_FLAG_ACK | TCP_FLAG_FIN, 4), sender, receiver, IPPROTO_TCP) == 1);
  assert(queued_fin.m_State == TCPStateCloseWait && queued_fin.m_StateAfterFIN == TCPStateLastAck);
  assert(queued_fin.m_bFINQueued && !queued_fin.m_bFINSent && queued_fin.m_bFINReceived);
  assert(queued_fin.m_nRCV_NXT == 1005 && queued_fin.m_RxQueue.IsEmpty());

  // Control: ordinary out-of-order data transfers ownership into reassembly.
  CTCPConnection retained;
  const unsigned before_retained = CNetBuffer::destroyed;
  assert(retained.PacketReceived(packet(1004, 500, TCP_FLAG_ACK | TCP_FLAG_PUSH, 3), sender, receiver, IPPROTO_TCP) == 1);
  assert(retained.m_ReassemblyQueue.Size() == 1 && retained.m_RxQueue.IsEmpty());
  assert(CNetBuffer::destroyed == before_retained);
  retained.m_bReadShutdown = true;
  assert(retained.PacketReceived(packet(1000, 500, TCP_FLAG_ACK | TCP_FLAG_PUSH, 4), sender, receiver, IPPROTO_TCP) == 1);
  assert(retained.m_nRCV_NXT == 1007 && retained.lastAcknowledgment == 1007);
  assert(retained.m_ReassemblyQueue.Size() == 0 && retained.m_RxQueue.IsEmpty());
  assert(CNetBuffer::destroyed == before_retained + 2);

  // The enabled-read queue owns precisely the original packet and only its payload.
  CNetBuffer *received = delivered.m_RxQueue.Dequeue();
  assert(received == in_order && received->GetLength() == 4);
  const u8 expected[] = {1, 2, 3, 4};
  assert(std::memcmp(received->GetPtr(), expected, sizeof(expected)) == 0);
  delete received;
  assert(CNetBuffer::alive == 0);
  std::puts("PASS");
}
'''


@unittest.skipUnless(CXX.is_file(), "host g++ unavailable")
class TcpShutdownPacketHostTests(unittest.TestCase):
    def test_actual_packet_received_override(self):
        source = SOURCE.read_text(encoding="utf-8")
        packet_received = method(source, "int CTCPConnection::PacketReceived (")
        # Header/flag layout comes from the same production source, not a parallel model.
        header_start = source.index("struct TTCPHeader\n")
        header_end = source.index("PACKED;", header_start) + len("PACKED;")
        header = "#define PACKED __attribute__((packed))\n" + source[header_start:header_end]
        options_start = source.index("struct TTCPOption\n")
        options_end = source.index("PACKED;", options_start) + len("PACKED;")
        definitions = source[options_start:options_end] + "\n"
        import re
        definitions += re.search(r"^#define TCP_MSS_S[^\n]+", source, re.M).group(0) + "\n#define IP_OPTION_SIZE 0\n"
        definitions += method(source, "boolean CTCPConnection::ScanOptions (") + "\n"
        fake = FAKE.replace("/* PRODUCTION_TCP_HEADER */", header)
        fake = "#include <circle/net/sizes.h>\n" + fake
        with host_temp_directory() as root:
            src = root / "test.cpp"
            exe = root / "test.exe"
            src.write_text(fake + definitions + packet_received + HARNESS, encoding="utf-8")
            env = os.environ.copy()
            env["PATH"] = str(CXX.parent) + os.pathsep + env.get("PATH", "")
            result = subprocess.run(
                # The production method intentionally does not use rReceiverIP.
                [str(CXX), "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-idirafter", str(ROOT / "lib/circle/include"), str(src), "-o", str(exe)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run(
                [str(exe)], cwd=root, env=env, capture_output=True, text=True, timeout=10
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()

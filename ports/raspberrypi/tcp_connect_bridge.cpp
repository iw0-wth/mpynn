// SPDX-License-Identifier: MIT
#include "tcp_connect_bridge.h"
#include "tcp_stream_bridge.h"
#include "network_bridge.h"
#include "socket_errno_bridge.h"
#include <circle/net/netsubsystem.h>
#include <circle/net/transportlayer.h>
#include <circle/net/ipaddress.h>
#include <circle/net/in.h>
#include <circle/sched/task.h>
#include <circle/sched/scheduler.h>
#include <circle/synchronize.h>

namespace {
constexpr unsigned slot_count = 4;
constexpr uint32_t max_generation = UINT32_MAX >> 2;
struct Job {
    CTransportLayer *transport = nullptr;
    uint32_t generation = 0;
    unsigned state = MPYNN_TCP_CONNECT_PENDING;
    int error = 0;
    int handle = -1;
    uint16_t local_port = 0;
};
Job jobs[slot_count];
Job *lookup(uint32_t token) {
    Job &job = jobs[token & 3];
    return job.transport && job.generation == (token >> 2) ? &job : nullptr;
}
void release(Job &job) {
    job.transport = nullptr;
    job.handle = -1;
    // Preserve generation: an old token must never identify a new job.
}

class ConnectWorker final : public CTask {
public:
    ConnectWorker(Job &job, const uint8_t *ip, unsigned port, uint16_t local_port)
        : m_job(job), m_ip(ip), m_port(static_cast<uint16_t>(port)), m_local_port(local_port) {}
    void Run() override {
        // CTask construction registers this worker; cooperative scheduling means
        // it cannot run before start finishes publishing the job and token.
        Job &job = m_job;
        if (job.state == MPYNN_TCP_CONNECT_ABANDONED) {
            release(job);
            return;
        }
        CNetSubSystem *net = mpynn_network_get();
        int result;
        if (!net || !net->IsRunning() || net->GetTransportLayer() != job.transport) {
            job.error = MPYNN_NODEV;
            job.state = MPYNN_TCP_CONNECT_FAILED;
            return;
        }
        // No cooperative yield from this check until native creation starts.
        if (m_local_port && job.transport->IsPortInUse(m_local_port, IPPROTO_TCP)) {
            job.error = MPYNN_ADDRINUSE;
            job.state = MPYNN_TCP_CONNECT_FAILED;
            return;
        }
        // This is the ONLY blocking call. Do not hold a lock across Connect:
        // CTCPConnection::Connect waits on an event and switches Circle tasks.
        result = job.transport->Connect(m_ip, m_port, m_local_port, IPPROTO_TCP);
        if (result >= 0) {
            // No yield between Connect and retain: pin this exact table entry
            // before publishing success or inspecting abandonment.
            int retained = job.transport->RetainConnection(result);
            if (retained < 0) {
                job.transport->Disconnect(result);
                result = retained;
            }
        }
        if (job.state == MPYNN_TCP_CONNECT_ABANDONED) {
            if (result >= 0) {
                job.transport->Disconnect(result);
                job.transport->ReleaseConnection(result);
            }
            release(job);
            return;
        }
        if (result < 0) {
            job.error = mpynn_socket_error_from_circle(result);
            job.state = MPYNN_TCP_CONNECT_FAILED;
        } else {
            job.handle = result; // Native handle zero is valid.
            job.state = MPYNN_TCP_CONNECT_SUCCEEDED;
        }
        // NEVER delete this or have release delete a worker. Actual Circle
        // TaskEntry marks termination AFTER Run returns and yields; scheduler
        // GetNextTask deletes terminated tasks only from another task's stack.
        // After publication/release, neither Run nor our destructor touches job.
    }
private:
    Job &m_job;
    CIPAddress m_ip;
    uint16_t m_port;
    uint16_t m_local_port;
};
}

extern "C" int mpynn_tcp_port_in_use(uint16_t port, unsigned *in_use) {
    // IsPortInUse locks the native table; never enter it from IRQ context.
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    if (!port || !in_use) return MPYNN_INVAL;
    CNetSubSystem *net = mpynn_network_get();
    if (!net || !net->IsRunning()) return MPYNN_NODEV;
    CTransportLayer *transport = net->GetTransportLayer();
    if (!transport) return MPYNN_NODEV;
    *in_use = transport->IsPortInUse(port, IPPROTO_TCP) ? 1u : 0u;
    return 0;
}

extern "C" int mpynn_tcp_connect_start(const uint8_t ip[4], unsigned port,
                                         uint32_t *token) {
    return mpynn_tcp_connect_start_bound(ip, port, 0, token);
}
extern "C" int mpynn_tcp_connect_start_bound(const uint8_t ip[4], unsigned port,
                                               uint16_t local_port, uint32_t *token) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    if (!ip || !token || !port || port > 65535 || ip[0] == 0 || ip[0] >= 224)
        return MPYNN_INVAL;
    if (!CScheduler::IsActive()) return MPYNN_NODEV;
    CNetSubSystem *net = mpynn_network_get();
    if (!net || !net->IsRunning()) return MPYNN_NODEV;
    CTransportLayer *transport = net->GetTransportLayer();
    if (!transport) return MPYNN_NODEV;
    if (local_port) {
        if (transport->IsPortInUse(local_port, IPPROTO_TCP)) return MPYNN_ADDRINUSE;
        for (const Job &existing : jobs) {
            if (existing.transport == transport && existing.local_port == local_port)
                return MPYNN_ADDRINUSE;
        }
    }
    for (unsigned i = 0; i < slot_count; ++i) {
        Job &job = jobs[i];
        if (job.transport || job.generation == max_generation) continue;
        ++job.generation;
        job.transport = transport;
        job.state = MPYNN_TCP_CONNECT_PENDING;
        job.error = 0;
        job.handle = -1;
        job.local_port = local_port;
        // Circle new/CTask stack allocation and scheduler AddTask assert/panic
        // on exhaustion: upstream provides no recoverable constructor failure.
        new ConnectWorker(job, ip, port, local_port);
        *token = (job.generation << 2) | i;
        return 0;
    }
    return MPYNN_MFILE;
}

extern "C" int mpynn_tcp_connect_poll(uint32_t token, unsigned *state, int *error) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    if (!state || !error) return MPYNN_INVAL;
    Job *job = lookup(token);
    if (!job) return MPYNN_BADF;
    *state = job->state;
    *error = job->error;
    return 0;
}

extern "C" int mpynn_tcp_connect_take(uint32_t token, int *handle) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    if (!handle) return MPYNN_INVAL;
    Job *job = lookup(token);
    if (!job) return MPYNN_BADF;
    if (job->state == MPYNN_TCP_CONNECT_FAILED) return job->error;
    if (job->state != MPYNN_TCP_CONNECT_SUCCEEDED) return MPYNN_AGAIN;
    *handle = job->handle;
    // Transfer the existing owner ref; release only the job slot.
    release(*job);
    return 0;
}

extern "C" int mpynn_tcp_connect_finish(uint32_t token, uint32_t *stream_token) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    if (!stream_token) return MPYNN_INVAL;
    Job *job = lookup(token);
    if (!job) return MPYNN_BADF;
    if (job->state == MPYNN_TCP_CONNECT_FAILED) return job->error;
    if (job->state != MPYNN_TCP_CONNECT_SUCCEEDED) return MPYNN_AGAIN;
    CNetSubSystem *net = mpynn_network_get();
    if (!net || net->GetTransportLayer() != job->transport) return MPYNN_NODEV;
    // claim allocates no GC/native memory and never yields. Publish stream first,
    // then invalidate job without dropping the existing Circle owner reference.
    int result = mpynn_tcp_stream_claim(job->handle, stream_token);
    if (result) return result;
    release(*job);
    return 0;
}

extern "C" int mpynn_tcp_connect_cancel(uint32_t token) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Job *job = lookup(token);
    if (!job) return MPYNN_BADF;
    if (job->state == MPYNN_TCP_CONNECT_PENDING ||
        job->state == MPYNN_TCP_CONNECT_ABANDONED) {
        job->state = MPYNN_TCP_CONNECT_ABANDONED;
        return 0;
    }
    int result = 0;
    // Actual CTCPConnection::Close does not wait/yield. Retain the slot until
    // Disconnect returns, then invalidate it even if Circle reports an error.
    if (job->handle >= 0) {
        result = job->transport->Disconnect(job->handle);
        int released = job->transport->ReleaseConnection(job->handle);
        if (result >= 0) result = released;
    }
    release(*job);
    return mpynn_socket_error_from_circle(result);
}

extern "C" int mpynn_tcp_connect_cancel_all(void) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    int first_error = 0;
    for (unsigned i = 0; i < slot_count; ++i) {
        if (!jobs[i].transport) continue;
        int error = mpynn_tcp_connect_cancel((jobs[i].generation << 2) | i);
        if (!first_error) first_error = error;
    }
    return first_error;
}

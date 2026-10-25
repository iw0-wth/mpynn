// SPDX-License-Identifier: MIT
#include "dns_bridge.h"
#include "network_bridge.h"
#include "socket_errno_bridge.h"
#include <circle/net/dnsclient.h>
#include <circle/net/netsubsystem.h>
#include <circle/net/ipaddress.h>
#include <circle/sched/task.h>
#include <circle/sched/scheduler.h>
#include <circle/synchronize.h>

namespace {
constexpr unsigned slot_count = 2;
constexpr uint32_t max_generation = UINT32_MAX >> 1;
enum State { Pending, Succeeded, Failed, Abandoned };
struct Job {
    CNetSubSystem *net = nullptr;
    uint32_t generation = 0;
    State state = Pending;
    int error = 0;
    uint8_t ip[4] = {};
};
Job jobs[slot_count];
Job *lookup(uint32_t token) {
    Job &job = jobs[token & 1];
    return job.net && job.generation == (token >> 1) ? &job : nullptr;
}
void release(Job &job) { job.net = nullptr; } // Preserve generation.
bool alnum(unsigned char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
           (c >= '0' && c <= '9');
}
bool valid_name(const char *name, size_t len) {
    if (!name || !len || len > 253) return false;
    size_t label = 0;
    for (size_t i = 0; i < len; ++i) {
        unsigned char c = static_cast<unsigned char>(name[i]);
        if (c == '.') {
            if (!label || !alnum(name[i-1])) return false;
            label = 0;
        } else {
            if (!alnum(c) && (c != '-' || !label)) return false;
            if (++label > 63) return false;
        }
    }
    return name[len-1] == '.' || alnum(name[len-1]);
}
class DNSWorker final : public CTask {
public:
    DNSWorker(Job &job, const char *name, size_t len) : m_job(job) {
        for (size_t i = 0; i < len; ++i) m_name[i] = name[i];
        m_name[len] = '\0';
    }
    void Run() override {
        Job &job = m_job;
        if (job.state == Abandoned) { release(job); return; }
        CNetSubSystem *net = mpynn_network_get();
        if (!net || net != job.net || !net->IsRunning()) {
            job.error = MPYNN_NODEV;
            job.state = Failed;
            return;
        }
        CDNSClient dns(net);
        CIPAddress ip;
        // The sole blocking operation, on a native Circle worker. No lock or
        // GC state crosses Resolve's scheduler sleeps. Network has platform life.
        bool success = dns.Resolve(m_name, &ip);
        if (job.state == Abandoned) { release(job); return; }
        if (success) {
            const uint8_t *bytes = ip.Get();
            for (unsigned i = 0; i < 4; ++i) job.ip[i] = bytes[i];
            job.state = Succeeded;
        } else {
            job.error = MPYNN_IO;
            job.state = Failed;
        }
        // Never self-delete. TaskEntry and scheduler own termination/deletion;
        // neither this destructor nor subsequent code accesses the released job.
    }
private:
    Job &m_job;
    char m_name[254];
};
}
extern "C" int mpynn_dns_start(const char *name, size_t len, uint32_t *token) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    if (!token || !valid_name(name, len)) return MPYNN_INVAL;
    if (!CScheduler::IsActive()) return MPYNN_NODEV;
    CNetSubSystem *net = mpynn_network_get();
    if (!net || !net->IsRunning()) return MPYNN_NODEV;
    for (unsigned i = 0; i < slot_count; ++i) {
        Job &job = jobs[i];
        if (job.net || job.generation == max_generation) continue;
        ++job.generation;
        job.net = net;
        job.state = Pending;
        job.error = 0;
        // Cooperative scheduling: CTask registers but cannot run until we yield.
        // Circle allocation/stack/task exhaustion asserts; no recoverable new.
        new DNSWorker(job, name, len);
        *token = (job.generation << 1) | i;
        return 0;
    }
    return MPYNN_MFILE;
}
extern "C" int mpynn_dns_finish(uint32_t token, uint8_t ip[4]) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    if (!ip) return MPYNN_INVAL;
    Job *job = lookup(token);
    if (!job) return MPYNN_BADF;
    if (job->state == Pending || job->state == Abandoned) return MPYNN_AGAIN;
    int error = job->error;
    if (job->state == Succeeded)
        for (unsigned i = 0; i < 4; ++i) ip[i] = job->ip[i];
    release(*job);
    return error;
}
extern "C" int mpynn_dns_cancel(uint32_t token) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    Job *job = lookup(token);
    if (!job) return MPYNN_BADF;
    if (job->state == Pending || job->state == Abandoned) job->state = Abandoned;
    else release(*job);
    return 0;
}
extern "C" int mpynn_dns_cancel_all(void) {
    if (CurrentExecutionLevel() != TASK_LEVEL) return MPYNN_BUSY;
    for (unsigned i = 0; i < slot_count; ++i)
        if (jobs[i].net) mpynn_dns_cancel((jobs[i].generation << 1) | i);
    return 0;
}

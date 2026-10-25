// SPDX-License-Identifier: MIT
// Host-only validation runtime: reserve enough GC heap for multi-megabyte models.
// This is not used by the Pi1B Circle port, whose heap is measured dynamically.
extern long heap_size;

#if defined(__GNUC__)
__attribute__((constructor))
#endif
static void mpynn_windows_set_gc_heap_size(void) {
    heap_size = 256L * 1024L * 1024L;
}

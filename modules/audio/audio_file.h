/*
 * SPDX-License-Identifier: MIT
 *
 * File-backed PCM audio source for MicroPython.
 */
#ifndef MPYNN_AUDIO_FILE_H
#define MPYNN_AUDIO_FILE_H

#include "py/obj.h"

/* Called by the parent port's VM poll/attachio hook. */
void audio_file_poll(void);

/* Called by the parent port during VM reset/deinitialisation. */
void audio_file_deinit(void);

/* Reset fencing around GC/VM teardown.  Call reset_begin before the parent
 * sweeps/finalises the heap and init0 immediately after mp_init(). */
void audio_file_reset_begin(void);
void audio_file_init0(void);

#endif /* MPYNN_AUDIO_FILE_H */

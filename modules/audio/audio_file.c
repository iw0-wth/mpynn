/*
 * SPDX-License-Identifier: MIT
 *
 * File-backed PCM audio source for MicroPython.  The source is deliberately
 * limited to VFS streams so it has no dependency on a board audio HAL.
 */
#include <stdint.h>
#include <string.h>

#include "py/builtin.h"
#include "py/obj.h"
#include "py/objarray.h"
#include "py/runtime.h"
#include "py/stream.h"

#include "audio_file.h"

#define AUDIO_DEFAULT_CHANNELS  (1)
#define AUDIO_DEFAULT_FREQUENCY (16000)
#define AUDIO_DEFAULT_SAMPLES   (320)
#define AUDIO_READ_BUFFER_MAX   (64 * 1024)

typedef enum {
    AUDIO_FORMAT_WAV,
    AUDIO_FORMAT_PCM,
} audio_format_t;

typedef struct {
    /* Python objects live in MP_STATE_VM root pointers below. */
    size_t buffer_size;
    size_t frame_bytes;
    size_t data_remaining;
    uint32_t frequency;
    uint16_t channels;
    audio_format_t format;
    uint32_t generation;
    bool initialized;
    bool resetting;
    bool streaming;
    bool eof;
    bool deinit_pending;
    bool in_poll;
    bool in_callback;
} audio_file_state_t;

static audio_file_state_t audio_state;

static void audio_raise(const mp_obj_type_t *type, mp_rom_error_text_t msg) {
    mp_raise_msg(type, msg);
}

static uint32_t read_le32(const byte *p) {
    return ((uint32_t)p[0]) | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint16_t read_le16(const byte *p) {
    return (uint16_t)(((uint16_t)p[0]) | ((uint16_t)p[1] << 8));
}

static bool id_is(const byte *id, const char *text) {
    return id[0] == (byte)text[0] && id[1] == (byte)text[1] &&
           id[2] == (byte)text[2] && id[3] == (byte)text[3];
}

static size_t audio_stream_read_some(mp_obj_t stream, void *buf, size_t size) {
    int error = 0;
    mp_uint_t n = mp_stream_read_exactly(stream, buf, size, &error);
    if (error != 0) {
        mp_raise_OSError(error);
    }
    return (size_t)n;
}

static void audio_stream_read_exact(mp_obj_t stream, void *buf, size_t size, const char *message) {
    if (audio_stream_read_some(stream, buf, size) != size) {
        audio_raise(&mp_type_ValueError, MP_ERROR_TEXT(message));
    }
}

static void audio_stream_skip(mp_obj_t stream, uint32_t size) {
    byte scratch[64];
    while (size != 0) {
        size_t part = size < sizeof(scratch) ? size : sizeof(scratch);
        audio_stream_read_exact(stream, scratch, part, "truncated WAV chunk");
        size -= (uint32_t)part;
    }
}

static bool audio_stream_seek(mp_obj_t stream, mp_off_t offset, int whence) {
    int error = 0;
    mp_off_t result = mp_stream_seek(stream, offset, whence, &error);
    return result >= 0 && error == 0;
}

static void audio_parse_wav(mp_obj_t stream, uint16_t requested_channels, uint32_t requested_frequency) {
    byte header[12];
    audio_stream_read_exact(stream, header, sizeof(header), "truncated RIFF header");
    if (!id_is(header, "RIFF") || !id_is(header + 8, "WAVE")) {
        audio_raise(&mp_type_ValueError, MP_ERROR_TEXT("invalid RIFF/WAVE file"));
    }

    uint32_t riff_size = read_le32(header + 4);
    if (riff_size < 4) {
        audio_raise(&mp_type_ValueError, MP_ERROR_TEXT("invalid RIFF size"));
    }
    uint64_t riff_end = (uint64_t)riff_size + 8u;
    /* Validate the declared RIFF boundary against the seekable VFS length so
     * a truncated file cannot look valid merely because its first data chunk
     * happens to be complete. Restore the chunk scan position afterward. */
    int end_error = 0;
    mp_off_t file_end = mp_stream_seek(stream, 0, MP_SEEK_END, &end_error);
    if (end_error != 0 || file_end < 0 || (uint64_t)file_end < riff_end ||
        !audio_stream_seek(stream, 12, MP_SEEK_SET)) {
        audio_raise(&mp_type_ValueError, MP_ERROR_TEXT("truncated RIFF file"));
    }
    bool got_fmt = false;
    bool got_data = false;
    mp_off_t data_offset = -1;
    uint16_t wav_channels = 0;
    uint32_t wav_frequency = 0;
    uint16_t wav_bits = 0;
    uint32_t data_size = 0;

    while (!got_data || !got_fmt) {
        byte chunk[8];
        if (audio_stream_read_some(stream, chunk, sizeof(chunk)) != sizeof(chunk)) {
            audio_raise(&mp_type_ValueError, MP_ERROR_TEXT("WAV data chunk missing"));
        }
        uint32_t size = read_le32(chunk + 4);
        int seek_error = 0;
        mp_off_t pos = mp_stream_seek(stream, 0, MP_SEEK_CUR, &seek_error);
        if (seek_error != 0) {
            audio_raise(&mp_type_ValueError, MP_ERROR_TEXT("WAV stream is not seekable"));
        }
        uint64_t padded_size = (uint64_t)size + (size & 1u);
        if (pos < 0 || (uint64_t)pos > riff_end || padded_size > riff_end - (uint64_t)pos) {
            audio_raise(&mp_type_ValueError, MP_ERROR_TEXT("WAV chunk exceeds RIFF"));
        }
        if (id_is(chunk, "fmt ")) {
            if (size < 16) {
                audio_raise(&mp_type_ValueError, MP_ERROR_TEXT("WAV fmt chunk too small"));
            }
            byte fmt[16];
            audio_stream_read_exact(stream, fmt, sizeof(fmt), "truncated WAV fmt chunk");
            uint16_t codec = read_le16(fmt + 0);
            wav_channels = read_le16(fmt + 2);
            wav_frequency = read_le32(fmt + 4);
            uint32_t byte_rate = read_le32(fmt + 8);
            uint16_t block_align = read_le16(fmt + 12);
            wav_bits = read_le16(fmt + 14);
            if (codec != 1 || wav_channels == 0 || wav_channels > 2 || wav_frequency == 0 || wav_bits != 16 ||
                block_align != (uint16_t)(wav_channels * 2u) ||
                (uint64_t)byte_rate != (uint64_t)wav_frequency * (uint32_t)block_align) {
                audio_raise(&mp_type_ValueError, MP_ERROR_TEXT("WAV must be PCM16 little-endian"));
            }
            audio_stream_skip(stream, size - 16u);
            got_fmt = true;
        } else if (id_is(chunk, "data")) {
            if (got_data) {
                audio_raise(&mp_type_ValueError, MP_ERROR_TEXT("duplicate WAV data chunk"));
            }
            data_size = size;
            data_offset = pos;
            got_data = true;
            /* Keep scanning through the declared RIFF extent in case fmt
             * follows data, then seek back to the first data chunk. */
            audio_stream_skip(stream, size);
        } else {
            audio_stream_skip(stream, size);
        }
        if ((size & 1u) != 0) {
            audio_stream_skip(stream, 1);
        }
    }
    if (!got_fmt) {
        audio_raise(&mp_type_ValueError, MP_ERROR_TEXT("WAV fmt chunk missing"));
    }
    if (requested_channels != wav_channels || requested_frequency != wav_frequency) {
        audio_raise(&mp_type_ValueError, MP_ERROR_TEXT("WAV format does not match init"));
    }
    if ((data_size % ((uint32_t)wav_channels * 2u)) != 0) {
        audio_raise(&mp_type_ValueError, MP_ERROR_TEXT("WAV data is not frame aligned"));
    }
    if (data_offset < 0 || !audio_stream_seek(stream, data_offset, MP_SEEK_SET)) {
        audio_raise(&mp_type_ValueError, MP_ERROR_TEXT("cannot seek to WAV data"));
    }
    audio_state.data_remaining = data_size;
    audio_state.channels = wav_channels;
    audio_state.frequency = wav_frequency;
    audio_state.frame_bytes = (size_t)wav_channels * 2u;
}

static void audio_open_file(mp_obj_t source) {
    mp_obj_t args[2] = { source, MP_OBJ_NEW_QSTR(MP_QSTR_rb) };
    MP_STATE_VM(audio_file_handle) = mp_builtin_open(2, args, (mp_map_t *)&mp_const_empty_map);
}

static void audio_free_buffer(void) {
    if (MP_STATE_VM(audio_file_data) != NULL) {
        m_del(byte, MP_STATE_VM(audio_file_data), audio_state.buffer_size);
    }
    MP_STATE_VM(audio_file_data) = NULL;
    audio_state.buffer_size = 0;
    MP_STATE_VM(audio_file_buffer) = mp_const_none;
}

/* Reset/deinit is called from VM teardown paths where an exception must never
 * escape.  Some VFS close implementations can raise, so contain that failure
 * and always clear the root. */
static void audio_close_file(void) {
    mp_obj_t handle = MP_STATE_VM(audio_file_handle);
    MP_STATE_VM(audio_file_handle) = mp_const_none;
    if (handle != mp_const_none && handle != MP_OBJ_NULL) {
        nlr_buf_t nlr;
        if (nlr_push(&nlr) == 0) {
            mp_stream_close(handle);
            nlr_pop();
        } else {
            /* Deliberately swallow close errors during reset/cleanup. */
        }
    }
}

static void audio_reset_state(void) {
    audio_state.streaming = false;
    audio_state.eof = false;
    audio_state.deinit_pending = false;
    audio_state.in_poll = false;
    audio_state.in_callback = false;
    MP_STATE_VM(audio_file_callback) = mp_const_none;
    audio_state.generation++;
    audio_close_file();
    audio_free_buffer();
    audio_state.initialized = false;
}

static mp_obj_t audio_init(size_t n_args, const mp_obj_t *pos_args, mp_map_t *kw_args) {
    enum { ARG_channels, ARG_frequency, ARG_samples, ARG_source, ARG_format };
    static const mp_arg_t allowed_args[] = {
        { MP_QSTR_channels, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = AUDIO_DEFAULT_CHANNELS} },
        { MP_QSTR_frequency, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = AUDIO_DEFAULT_FREQUENCY} },
        { MP_QSTR_samples, MP_ARG_KW_ONLY | MP_ARG_INT, {.u_int = AUDIO_DEFAULT_SAMPLES} },
        { MP_QSTR_source, MP_ARG_KW_ONLY | MP_ARG_REQUIRED | MP_ARG_OBJ, {.u_obj = MP_OBJ_NULL} },
        { MP_QSTR_format, MP_ARG_KW_ONLY | MP_ARG_OBJ, {.u_rom_obj = MP_ROM_QSTR(MP_QSTR_wav)} },
    };
    mp_arg_val_t args[MP_ARRAY_SIZE(allowed_args)];
    if (audio_state.resetting) {
        audio_raise(&mp_type_RuntimeError, MP_ERROR_TEXT("audio unavailable during VM reset"));
    }
    if (audio_state.in_poll || audio_state.in_callback) {
        audio_raise(&mp_type_RuntimeError, MP_ERROR_TEXT("audio operation is reentrant"));
    }
    mp_arg_parse_all(n_args, pos_args, kw_args, MP_ARRAY_SIZE(allowed_args), allowed_args, args);

    if (args[ARG_channels].u_int < 1 || args[ARG_channels].u_int > 2 ||
        args[ARG_frequency].u_int <= 0 || args[ARG_samples].u_int <= 0 ||
        (size_t)args[ARG_samples].u_int > (AUDIO_READ_BUFFER_MAX / ((size_t)args[ARG_channels].u_int * 2u))) {
        audio_raise(&mp_type_ValueError, MP_ERROR_TEXT("invalid audio parameters"));
    }
    if (!mp_obj_is_str(args[ARG_format].u_obj)) {
        audio_raise(&mp_type_ValueError, MP_ERROR_TEXT("format must be 'wav' or 'pcm'"));
    }
    size_t format_len;
    const char *format = mp_obj_str_get_data(args[ARG_format].u_obj, &format_len);
    audio_format_t audio_format;
    if (format_len == 3 && memcmp(format, "wav", 3) == 0) {
        audio_format = AUDIO_FORMAT_WAV;
    } else if (format_len == 3 && memcmp(format, "pcm", 3) == 0) {
        audio_format = AUDIO_FORMAT_PCM;
    } else {
        audio_raise(&mp_type_ValueError, MP_ERROR_TEXT("format must be 'wav' or 'pcm'"));
    }

    /* Validate all scalar arguments before opening a VFS object. */
    if (audio_state.initialized || audio_state.streaming) {
        audio_reset_state();
    }
    MP_STATE_VM(audio_file_handle) = mp_const_none;
    MP_STATE_VM(audio_file_callback) = mp_const_none;
    audio_state.channels = (uint16_t)args[ARG_channels].u_int;
    audio_state.frequency = (uint32_t)args[ARG_frequency].u_int;
    audio_state.format = audio_format;
    audio_state.frame_bytes = (size_t)audio_state.channels * 2u;
    audio_state.buffer_size = (size_t)args[ARG_samples].u_int * audio_state.frame_bytes;
    audio_state.generation++;

    nlr_buf_t nlr;
    if (nlr_push(&nlr) != 0) {
        audio_close_file();
        audio_free_buffer();
        audio_state.initialized = false;
        nlr_jump(nlr.ret_val);
    }
    audio_open_file(args[ARG_source].u_obj);
    if (audio_format == AUDIO_FORMAT_WAV) {
        audio_parse_wav(MP_STATE_VM(audio_file_handle), audio_state.channels, audio_state.frequency);
    } else {
        audio_state.data_remaining = (size_t)-1;
    }
    MP_STATE_VM(audio_file_data) = m_new(byte, audio_state.buffer_size);
    MP_STATE_VM(audio_file_buffer) = mp_obj_new_bytearray_by_ref(audio_state.buffer_size, MP_STATE_VM(audio_file_data));
    audio_state.initialized = true;
    nlr_pop();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_KW(audio_init_obj, 0, audio_init);

static void audio_file_poll_impl(void) {
    if (audio_state.resetting || !audio_state.initialized || !audio_state.streaming || audio_state.eof ||
        audio_state.in_poll || audio_state.in_callback) {
        return;
    }
    audio_state.in_poll = true;
    size_t want = audio_state.buffer_size;
    if (audio_state.format == AUDIO_FORMAT_WAV && audio_state.data_remaining < want) {
        want = audio_state.data_remaining;
    }
    if (want == 0) {
        audio_state.eof = true;
        audio_state.streaming = false;
        MP_STATE_VM(audio_file_callback) = mp_const_none;
        audio_state.in_poll = false;
        return;
    }
    nlr_buf_t read_nlr;
    if (nlr_push(&read_nlr) != 0) {
        /* A VFS failure ends the stream without leaving the poll guard set or
         * allowing an exception to escape an attachio/poll hook. */
        audio_state.in_poll = false;
        audio_state.streaming = false;
        audio_state.eof = true;
        MP_STATE_VM(audio_file_callback) = mp_const_none;
        return;
    }
    size_t got = audio_stream_read_some(MP_STATE_VM(audio_file_handle), MP_STATE_VM(audio_file_data), want);
    nlr_pop();
    if (got == 0 || (got % audio_state.frame_bytes) != 0) {
        audio_state.eof = true;
        audio_state.streaming = false;
        MP_STATE_VM(audio_file_callback) = mp_const_none;
        audio_state.in_poll = false;
        return;
    }
    if (audio_state.format == AUDIO_FORMAT_WAV) {
        audio_state.data_remaining -= got;
    }
    /* Pass exactly the bytes read: a short final read is never padded with
     * stale buffer contents or synthetic zero samples. */
    mp_obj_t callback_buffer = mp_obj_new_bytes(MP_STATE_VM(audio_file_data), got);
    MP_STATE_VM(audio_file_buffer) = callback_buffer;
    uint32_t generation = audio_state.generation;
    mp_obj_t callback = MP_STATE_VM(audio_file_callback);
    audio_state.in_callback = true;
    mp_obj_t result = mp_call_function_1_protected(callback, callback_buffer);
    audio_state.in_callback = false;
    if (result == MP_OBJ_NULL) {
        /* mp_call_function_1_protected reports the callback exception and
         * returns NULL. Never retry a failed callback on the next poll. */
        audio_state.streaming = false;
        audio_state.eof = true;
        audio_state.generation++;
        MP_STATE_VM(audio_file_callback) = mp_const_none;
    }
    if (result == MP_OBJ_NULL || generation != audio_state.generation || !audio_state.streaming) {
        audio_state.in_poll = false;
        if (audio_state.deinit_pending) {
            audio_reset_state();
        }
        return;
    }
    if (audio_state.format == AUDIO_FORMAT_WAV && audio_state.data_remaining == 0) {
        audio_state.eof = true;
        audio_state.streaming = false;
        MP_STATE_VM(audio_file_callback) = mp_const_none;
    }
    audio_state.in_poll = false;
}

void audio_file_poll(void) {
    if (audio_state.resetting || !audio_state.initialized || !audio_state.streaming || audio_state.eof ||
        audio_state.in_poll || audio_state.in_callback) {
        return;
    }
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        audio_file_poll_impl();
        nlr_pop();
    } else {
        /* attachio/VM-return hooks cannot let allocation, VFS, or callback
         * failures escape. Stop this generation and leave all guards clear. */
        audio_state.in_poll = false;
        audio_state.in_callback = false;
        audio_state.streaming = false;
        audio_state.eof = true;
        audio_state.generation++;
        MP_STATE_VM(audio_file_callback) = mp_const_none;
    }
}

static mp_obj_t audio_start_streaming(mp_obj_t callback) {
    if (audio_state.resetting) {
        audio_raise(&mp_type_RuntimeError, MP_ERROR_TEXT("audio unavailable during VM reset"));
    }
    if (!audio_state.initialized) {
        audio_raise(&mp_type_RuntimeError, MP_ERROR_TEXT("audio is not initialized"));
    }
    if (!mp_obj_is_callable(callback)) {
        audio_raise(&mp_type_TypeError, MP_ERROR_TEXT("callback must be callable"));
    }
    if (audio_state.in_poll || audio_state.in_callback) {
        audio_raise(&mp_type_RuntimeError, MP_ERROR_TEXT("audio operation is reentrant"));
    }
    audio_state.generation++;
    MP_STATE_VM(audio_file_callback) = callback;
    audio_state.streaming = true;
    audio_state.eof = false;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(audio_start_streaming_obj, audio_start_streaming);

static mp_obj_t audio_stop_streaming(void) {
    if (audio_state.in_poll || audio_state.in_callback) {
        audio_state.generation++;
        audio_state.streaming = false;
        MP_STATE_VM(audio_file_callback) = mp_const_none;
        return mp_const_none;
    }
    audio_state.generation++;
    audio_state.streaming = false;
    MP_STATE_VM(audio_file_callback) = mp_const_none;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(audio_stop_streaming_obj, audio_stop_streaming);

void audio_file_deinit(void) {
    if (audio_state.in_callback || audio_state.in_poll) {
        audio_state.generation++;
        audio_state.streaming = false;
        audio_state.deinit_pending = true;
        MP_STATE_VM(audio_file_callback) = mp_const_none;
        return;
    }
    audio_reset_state();
    MP_STATE_VM(audio_file_handle) = mp_const_none;
    MP_STATE_VM(audio_file_callback) = mp_const_none;
    MP_STATE_VM(audio_file_buffer) = mp_const_none;
    MP_STATE_VM(audio_file_data) = NULL;
}

void audio_file_reset_begin(void) {
    audio_state.resetting = true;
    audio_file_deinit();
    /* Keep the fence asserted until the parent has called mp_init(). */
}

void audio_file_init0(void) {
    /* mp_init() has established fresh root storage. Never inspect an object
     * left by the previous VM, and make the C state match those roots. */
    MP_STATE_VM(audio_file_handle) = mp_const_none;
    MP_STATE_VM(audio_file_callback) = mp_const_none;
    MP_STATE_VM(audio_file_buffer) = mp_const_none;
    MP_STATE_VM(audio_file_data) = NULL;
    audio_state = (audio_file_state_t){0};
    audio_state.resetting = false;
}

static mp_obj_t audio_deinit(void) {
    if (audio_state.in_poll || audio_state.in_callback) {
        audio_raise(&mp_type_RuntimeError, MP_ERROR_TEXT("audio operation is reentrant"));
    }
    audio_file_deinit();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(audio_deinit_obj, audio_deinit);

static mp_obj_t audio_poll(void) {
    if (audio_state.in_poll || audio_state.in_callback) {
        audio_raise(&mp_type_RuntimeError, MP_ERROR_TEXT("audio operation is reentrant"));
    }
    audio_file_poll();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(audio_poll_obj, audio_poll);

static mp_obj_t audio_is_streaming(void) {
    return mp_obj_new_bool(audio_state.initialized && audio_state.streaming);
}
static MP_DEFINE_CONST_FUN_OBJ_0(audio_is_streaming_obj, audio_is_streaming);

static mp_obj_t audio_eof(void) {
    return mp_obj_new_bool(audio_state.eof);
}
static MP_DEFINE_CONST_FUN_OBJ_0(audio_eof_obj, audio_eof);

static const mp_rom_map_elem_t audio_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_audio) },
    { MP_ROM_QSTR(MP_QSTR_init), MP_ROM_PTR(&audio_init_obj) },
    { MP_ROM_QSTR(MP_QSTR_start_streaming), MP_ROM_PTR(&audio_start_streaming_obj) },
    { MP_ROM_QSTR(MP_QSTR_stop_streaming), MP_ROM_PTR(&audio_stop_streaming_obj) },
    { MP_ROM_QSTR(MP_QSTR_deinit), MP_ROM_PTR(&audio_deinit_obj) },
    /* Explicit poll is useful for ports whose attachio hook is not automatic. */
    { MP_ROM_QSTR(MP_QSTR_poll), MP_ROM_PTR(&audio_poll_obj) },
    { MP_ROM_QSTR(MP_QSTR_is_streaming), MP_ROM_PTR(&audio_is_streaming_obj) },
    { MP_ROM_QSTR(MP_QSTR_eof), MP_ROM_PTR(&audio_eof_obj) },
};
static MP_DEFINE_CONST_DICT(audio_globals, audio_globals_table);
const mp_obj_module_t audio_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_t)&audio_globals,
};

MP_REGISTER_ROOT_POINTER(mp_obj_t audio_file_handle);
MP_REGISTER_ROOT_POINTER(mp_obj_t audio_file_callback);
MP_REGISTER_ROOT_POINTER(mp_obj_t audio_file_buffer);
MP_REGISTER_ROOT_POINTER(byte * audio_file_data);
MP_REGISTER_MODULE(MP_QSTR_audio, audio_module);

/*
 * This file is part of the MicroPython project, http://micropython.org/
 *
 * The MIT License (MIT)
 *
 * Copyright (c) 2014 Damien P. George
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "py/objtuple.h"
#include "py/objlist.h"
#include "py/runtime.h"
#include "py/stream.h"
#include "py/mperrno.h"

#if MICROPY_PY_NETWORK && MICROPY_PY_SOCKET && !MICROPY_PY_LWIP

#include "shared/netutils/netutils.h"
#include "extmod/modnetwork.h"
#if defined(MICROPY_PORT_SOCKET_SENDALL) || defined(MICROPY_PORT_SOCKET_GETPEERNAME) || defined(MICROPY_PORT_SOCKET_GETSOCKNAME) || defined(MICROPY_PORT_SOCKET_SHUTDOWN)
#include "socket_port.h"
#endif

/******************************************************************************/
// socket class

static const mp_obj_type_t socket_type;

static void socket_print(const mp_print_t *print, mp_obj_t self_in, mp_print_kind_t kind) {
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(self_in);
    mp_printf(print, "<socket fd=%d timeout=%d domain=%d type=%d proto=%d bound=%b>",
        self->fileno, self->timeout, self->domain, self->type, self->proto, self->bound);
}

// constructor socket(domain=AF_INET, type=SOCK_STREAM, proto=0)
static mp_obj_t socket_make_new(const mp_obj_type_t *type, size_t n_args, size_t n_kw, const mp_obj_t *args) {
    mp_arg_check_num(n_args, n_kw, 0, 3, false);
    (void)type;
    // domain/type/proto are 5-bit fields in mod_network_socket_obj_t. Reject
    // values that would otherwise wrap into a different socket configuration.
    if (n_args > 0) {
        mp_int_t value = mp_obj_get_int(args[0]);
        if (value < 0 || value > 31) mp_raise_ValueError(MP_ERROR_TEXT("socket domain out of range"));
    }
    if (n_args > 1) {
        mp_int_t value = mp_obj_get_int(args[1]);
        if (value < 0 || value > 31) mp_raise_ValueError(MP_ERROR_TEXT("socket type out of range"));
    }
    if (n_args > 2) {
        mp_int_t value = mp_obj_get_int(args[2]);
        if (value < 0 || value > 31) mp_raise_ValueError(MP_ERROR_TEXT("socket protocol out of range"));
    }

    // create socket object (not bound to any NIC yet)
    mod_network_socket_obj_t *s = mp_obj_malloc_with_finaliser(mod_network_socket_obj_t, &socket_type);
    s->nic = MP_OBJ_NULL;
    s->nic_protocol = NULL;
    s->domain = MOD_NETWORK_AF_INET;
    s->type = MOD_NETWORK_SOCK_STREAM;
    s->proto = 0;
    s->bound = false;
    s->fileno = -1;
    if (n_args > 0) {
        s->domain = mp_obj_get_int(args[0]);
        if (n_args > 1) {
            s->type = mp_obj_get_int(args[1]);
            if (n_args > 2) {
                s->proto = mp_obj_get_int(args[2]);
            }
        }
    }
    s->timeout = -1;
    s->callback = MP_OBJ_NULL;
    s->state = MOD_NETWORK_SS_NEW;
    #if MICROPY_PY_SOCKET_EXTENDED_STATE
    s->_private = NULL;
    #endif

    return MP_OBJ_FROM_PTR(s);
}

static void socket_select_nic(mod_network_socket_obj_t *self, const byte *ip) {
    if (self->nic == MP_OBJ_NULL) {
        // select NIC based on IP
        self->nic = mod_network_find_nic(ip);
        self->nic_protocol = (mod_network_nic_protocol_t *)MP_OBJ_TYPE_GET_SLOT(mp_obj_get_type(self->nic), protocol);

        // call the NIC to open the socket
        int _errno;
        if (self->nic_protocol->socket(self, &_errno) != 0) {
            // Failed creation must not leave a selected NIC that bypasses socket()
            // on the next attempt. The NIC owns rollback of failed creation.
            self->nic = MP_OBJ_NULL;
            self->nic_protocol = NULL;
            mp_raise_OSError(_errno);
        }

        #if MICROPY_PY_SOCKET_EXTENDED_STATE
        // if a timeout was set before binding a NIC, call settimeout to reset it
        if (self->timeout != -1 && self->nic_protocol->settimeout(self, self->timeout, &_errno) != 0) {
            // Creation succeeded, so dispose of its resources before raising.
            self->nic_protocol->close(self);
            self->nic = MP_OBJ_NULL;
            self->nic_protocol = NULL;
            self->state = MOD_NETWORK_SS_CLOSED;
            mp_raise_OSError(_errno);
        }
        #endif
    }
}

// Port-owned endpoint parser: upstream netutils narrows large octets and accepts
// trailing text. Do not silently send to a different address than requested.
static mp_uint_t socket_parse_address(mp_obj_t addr_in, uint8_t ip[4]) {
    mp_obj_t *items;
    mp_obj_get_array_fixed_n(addr_in, 2, &items);
    size_t length;
    const char *text = mp_obj_str_get_data(items[0], &length);
    mp_int_t port = mp_obj_get_int(items[1]);
    if (port < 0 || port > 65535) mp_raise_ValueError(MP_ERROR_TEXT("port out of range"));
    uint8_t parsed[4] = {0};
    if (length != 0) {
        size_t position = 0;
        for (unsigned group = 0; group < 4; ++group) {
            unsigned octet = 0, digits = 0;
            while (position < length && text[position] >= '0' && text[position] <= '9') {
                octet = octet * 10 + (unsigned)(text[position++] - '0');
                if (++digits > 3 || octet > 255)
                    mp_raise_ValueError(MP_ERROR_TEXT("invalid IPv4 address"));
            }
            if (!digits || (group < 3 ? position == length || text[position++] != '.' : position != length))
                mp_raise_ValueError(MP_ERROR_TEXT("invalid IPv4 address"));
            parsed[group] = (uint8_t)octet;
        }
    }
    memcpy(ip, parsed, sizeof(parsed));
    return (mp_uint_t)port;
}

// method socket.bind(address)
static mp_obj_t socket_bind(mp_obj_t self_in, mp_obj_t addr_in) {
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->state == MOD_NETWORK_SS_CLOSED) mp_raise_OSError(MP_EBADF);

    // get address
    uint8_t ip[MOD_NETWORK_IPADDR_BUF_SIZE];
    mp_uint_t port = socket_parse_address(addr_in, ip);

    // check if we need to select a NIC
    socket_select_nic(self, ip);

    // call the NIC to bind the socket
    int _errno;
    if (self->nic_protocol->bind(self, ip, port, &_errno) != 0) {
        mp_raise_OSError(_errno);
    }

    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(socket_bind_obj, socket_bind);

// method socket.listen([backlog])
static mp_obj_t socket_listen(size_t n_args, const mp_obj_t *args) {
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(args[0]);
    if (self->state == MOD_NETWORK_SS_CLOSED) mp_raise_OSError(MP_EBADF);
    if (self->domain != MOD_NETWORK_AF_INET) mp_raise_OSError(MP_EAFNOSUPPORT);
    if (self->type != MOD_NETWORK_SOCK_STREAM || (self->proto != 0 && self->proto != 6))
        mp_raise_OSError(MP_EOPNOTSUPP);

    mp_int_t backlog = MICROPY_PY_SOCKET_LISTEN_BACKLOG_DEFAULT;
    if (n_args > 1) {
        backlog = mp_obj_get_int(args[1]);
        backlog = (backlog < 0) ? 0 : backlog;
    }
    if (self->nic == MP_OBJ_NULL) {
        uint8_t wildcard[4] = {0};
        socket_select_nic(self, wildcard);
    }

    int _errno;
    if (self->nic_protocol->listen(self, backlog, &_errno) != 0) {
        mp_raise_OSError(_errno);
    }

    // set socket state
    self->state = MOD_NETWORK_SS_LISTENING;

    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(socket_listen_obj, 1, 2, socket_listen);

// method socket.accept()
static mp_obj_t socket_accept(mp_obj_t self_in) {
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->state == MOD_NETWORK_SS_CLOSED) mp_raise_OSError(MP_EBADF);
    if (self->domain != MOD_NETWORK_AF_INET) mp_raise_OSError(MP_EAFNOSUPPORT);
    if (self->type != MOD_NETWORK_SOCK_STREAM || (self->proto != 0 && self->proto != 6))
        mp_raise_OSError(MP_EOPNOTSUPP);
    if (self->nic == MP_OBJ_NULL || self->state != MOD_NETWORK_SS_LISTENING)
        mp_raise_OSError(MP_EINVAL);

    // create new socket object
    // starts with empty NIC so that finaliser doesn't run close() method if accept() fails
    mod_network_socket_obj_t *socket2 = mp_obj_malloc_with_finaliser(mod_network_socket_obj_t, &socket_type);
    socket2->nic = MP_OBJ_NULL;
    socket2->nic_protocol = NULL;

    // set the same address family, socket type and protocol as parent
    socket2->domain = self->domain;
    socket2->type = self->type;
    socket2->proto = self->proto;
    socket2->bound = false;
    socket2->fileno = -1;
    socket2->timeout = -1;
    socket2->callback = MP_OBJ_NULL;
    socket2->state = MOD_NETWORK_SS_NEW;
    #if MICROPY_PY_SOCKET_EXTENDED_STATE
    socket2->_private = NULL;
    #endif

    // accept incoming connection
    uint8_t ip[MOD_NETWORK_IPADDR_BUF_SIZE];
    mp_uint_t port;
    int _errno;
    if (self->nic_protocol->accept(self, socket2, ip, &port, &_errno) != 0) {
        mp_raise_OSError(_errno);
    }

    // new socket has valid state, so set the NIC to the same as parent
    socket2->nic = self->nic;
    socket2->nic_protocol = self->nic_protocol;

    // Native ownership is already transferred. If result construction runs out
    // of memory, close the accepted stream immediately rather than leave it live
    // until an eventual finalizer. Nothing here closes/restarts the parent.
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        mp_obj_tuple_t *client = MP_OBJ_TO_PTR(mp_obj_new_tuple(2, NULL));
        client->items[0] = MP_OBJ_FROM_PTR(socket2);
        client->items[1] = netutils_format_inet_addr(ip, port, NETUTILS_BIG);
        nlr_pop();
        return MP_OBJ_FROM_PTR(client);
    }
    socket2->nic_protocol->close(socket2);
    socket2->nic = MP_OBJ_NULL;
    socket2->nic_protocol = NULL;
    socket2->state = MOD_NETWORK_SS_CLOSED;
    nlr_jump(nlr.ret_val);
}
static MP_DEFINE_CONST_FUN_OBJ_1(socket_accept_obj, socket_accept);

// method socket.connect(address)
static mp_obj_t socket_connect(mp_obj_t self_in, mp_obj_t addr_in) {
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->state == MOD_NETWORK_SS_CLOSED) mp_raise_OSError(MP_EBADF);

    // get address
    uint8_t ip[MOD_NETWORK_IPADDR_BUF_SIZE];
    mp_uint_t port = socket_parse_address(addr_in, ip);

    // check if we need to select a NIC
    socket_select_nic(self, ip);

    // call the NIC to connect the socket
    int _errno;
    if (self->nic_protocol->connect(self, ip, port, &_errno) != 0) {
        mp_raise_OSError(_errno);
    }

    // set socket state
    self->state = MOD_NETWORK_SS_CONNECTED;

    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(socket_connect_obj, socket_connect);

// method socket.send(bytes)
static mp_obj_t socket_send(mp_obj_t self_in, mp_obj_t buf_in) {
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->nic == MP_OBJ_NULL) {
        // not connected
        mp_raise_OSError(MP_EPIPE);
    }
    mp_buffer_info_t bufinfo;
    mp_get_buffer_raise(buf_in, &bufinfo, MP_BUFFER_READ);
    int _errno;
    mp_uint_t ret = self->nic_protocol->send(self, bufinfo.buf, bufinfo.len, &_errno);
    if (ret == -1) {
        mp_raise_OSError(_errno);
    }
    return mp_obj_new_int_from_uint(ret);
}
static MP_DEFINE_CONST_FUN_OBJ_2(socket_send_obj, socket_send);

static mp_obj_t socket_sendall(mp_obj_t self_in, mp_obj_t buf_in) {
    #ifdef MICROPY_PORT_SOCKET_SENDALL
    return MICROPY_PORT_SOCKET_SENDALL(self_in, buf_in);
    #else
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->nic == MP_OBJ_NULL) {
        // not connected
        mp_raise_OSError(MP_EPIPE);
    }
    mp_buffer_info_t bufinfo;
    mp_get_buffer_raise(buf_in, &bufinfo, MP_BUFFER_READ);

    int _errno;
    mp_uint_t ret = 0;
    if (self->timeout == 0) {
        ret = self->nic_protocol->send(self, bufinfo.buf, bufinfo.len, &_errno);
        if (ret == -1) {
            mp_raise_OSError(_errno);
        } else if (ret > bufinfo.len) {
            mp_raise_OSError(MP_EIO);
        } else if (bufinfo.len > ret) {
            mp_raise_OSError(MP_EAGAIN);
        }
    } else {
        // TODO: In CPython3.5, socket timeout should apply to the
        // entire sendall() operation, not to individual send() chunks.
        while (bufinfo.len != 0) {
            ret = self->nic_protocol->send(self, bufinfo.buf, bufinfo.len, &_errno);
            if (ret == -1) {
                mp_raise_OSError(_errno);
            }
            if (ret == 0) {
                mp_raise_OSError(MP_EPIPE);
            }
            if (ret > bufinfo.len) {
                mp_raise_OSError(MP_EIO);
            }
            bufinfo.len -= ret;
            bufinfo.buf = (char *)bufinfo.buf + ret;
        }
    }
    return mp_const_none;
    #endif
}
static MP_DEFINE_CONST_FUN_OBJ_2(socket_sendall_obj, socket_sendall);

// method socket.recv(bufsize)
static mp_obj_t socket_recv(mp_obj_t self_in, mp_obj_t len_in) {
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->nic == MP_OBJ_NULL) {
        // not connected
        mp_raise_OSError(MP_ENOTCONN);
    }
    mp_int_t len = mp_obj_get_int(len_in);
    if (len < 0) {
        mp_raise_ValueError(MP_ERROR_TEXT("negative buffer size"));
    }
    vstr_t vstr;
    vstr_init_len(&vstr, len);
    int _errno;
    mp_uint_t ret = self->nic_protocol->recv(self, (byte *)vstr.buf, len, &_errno);
    if (ret == (mp_uint_t)-1) {
        vstr_clear(&vstr);
        mp_raise_OSError(_errno);
    }
    if (ret > vstr.len) {
        vstr_clear(&vstr);
        mp_raise_OSError(MP_EIO);
    }
    if (ret == 0) {
        vstr_clear(&vstr);
        return mp_const_empty_bytes;
    }
    vstr.len = ret;
    return mp_obj_new_bytes_from_vstr(&vstr);
}
static MP_DEFINE_CONST_FUN_OBJ_2(socket_recv_obj, socket_recv);

// Buffer-oriented socket receives perform one NIC operation, unlike readinto()
// which is allowed to fill the whole buffer via multiple stream reads.
static mp_obj_t socket_receive_into(size_t n_args, const mp_obj_t *args, bool with_peer) {
    mp_buffer_info_t buffer;
    mp_get_buffer_raise(args[1], &buffer, MP_BUFFER_WRITE);
    mp_int_t requested = n_args > 2 ? mp_obj_get_int(args[2]) : 0;
    if (requested < 0 || (mp_uint_t)requested > buffer.len) {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid receive size"));
    }
    if (n_args > 3 && mp_obj_get_int(args[3]) != 0) mp_raise_OSError(MP_EOPNOTSUPP);
    size_t capacity = requested == 0 ? buffer.len : (size_t)requested;
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(args[0]);
    if (self->state == MOD_NETWORK_SS_CLOSED) mp_raise_OSError(MP_EBADF);
    if (self->nic == MP_OBJ_NULL) mp_raise_OSError(MP_ENOTCONN);
    int error;
    byte ip[4];
    mp_uint_t port;
    mp_uint_t count = with_peer
        ? self->nic_protocol->recvfrom(self, buffer.buf, capacity, ip, &port, &error)
        : self->nic_protocol->recv(self, buffer.buf, capacity, &error);
    if (count == (mp_uint_t)-1) mp_raise_OSError(error);
    if (count > capacity) mp_raise_OSError(MP_EIO);
    mp_obj_t result = mp_obj_new_int_from_uint(count);
    if (!with_peer) return result;
    mp_obj_t values[2] = {result, netutils_format_inet_addr(ip, port, NETUTILS_BIG)};
    return mp_obj_new_tuple(2, values);
}
static mp_obj_t socket_recv_into(size_t n_args, const mp_obj_t *args) {
    return socket_receive_into(n_args, args, false);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(socket_recv_into_obj, 2, 4, socket_recv_into);
static mp_obj_t socket_recvfrom_into(size_t n_args, const mp_obj_t *args) {
    return socket_receive_into(n_args, args, true);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(socket_recvfrom_into_obj, 2, 4, socket_recvfrom_into);

// method socket.sendto(bytes, address)
static mp_obj_t socket_sendto(mp_obj_t self_in, mp_obj_t data_in, mp_obj_t addr_in) {
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->state == MOD_NETWORK_SS_CLOSED) mp_raise_OSError(MP_EBADF);

    // get the data
    mp_buffer_info_t bufinfo;
    mp_get_buffer_raise(data_in, &bufinfo, MP_BUFFER_READ);

    // get address
    uint8_t ip[MOD_NETWORK_IPADDR_BUF_SIZE];
    mp_uint_t port = socket_parse_address(addr_in, ip);

    // check if we need to select a NIC
    socket_select_nic(self, ip);

    // call the NIC to sendto
    int _errno;
    mp_int_t ret = self->nic_protocol->sendto(self, bufinfo.buf, bufinfo.len, ip, port, &_errno);
    if (ret == -1) {
        mp_raise_OSError(_errno);
    }

    return mp_obj_new_int(ret);
}
static MP_DEFINE_CONST_FUN_OBJ_3(socket_sendto_obj, socket_sendto);

// method socket.recvfrom(bufsize)
static mp_obj_t socket_recvfrom(mp_obj_t self_in, mp_obj_t len_in) {
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->nic == MP_OBJ_NULL) {
        // not connected
        mp_raise_OSError(MP_ENOTCONN);
    }
    mp_int_t len = mp_obj_get_int(len_in);
    if (len < 0) {
        mp_raise_ValueError(MP_ERROR_TEXT("negative buffer size"));
    }
    vstr_t vstr;
    vstr_init_len(&vstr, len);
    byte ip[4];
    mp_uint_t port;
    int _errno;
    mp_int_t ret = self->nic_protocol->recvfrom(self, (byte *)vstr.buf, vstr.len, ip, &port, &_errno);
    if (ret == -1) {
        vstr_clear(&vstr);
        mp_raise_OSError(_errno);
    }
    if (ret < 0 || (mp_uint_t)ret > vstr.len) {
        vstr_clear(&vstr);
        mp_raise_OSError(MP_EIO);
    }
    mp_obj_t tuple[2];
    if (ret == 0) {
        vstr_clear(&vstr);
        tuple[0] = mp_const_empty_bytes;
    } else {
        vstr.len = ret;
        tuple[0] = mp_obj_new_bytes_from_vstr(&vstr);
    }
    tuple[1] = netutils_format_inet_addr(ip, port, NETUTILS_BIG);
    return mp_obj_new_tuple(2, tuple);
}
static MP_DEFINE_CONST_FUN_OBJ_2(socket_recvfrom_obj, socket_recvfrom);

// Normalize fixed-width timeout buffers before NIC selection, including unaligned
// buffers. Zero means an infinite timeout; positive timeval fractions round up
// so millisecond resolution never expires earlier than the requested interval.
static mp_int_t socket_timeout_buffer_ms(const void *buffer, size_t length) {
    if (!buffer) mp_raise_OSError(MP_EINVAL);
    int64_t milliseconds;
    if (length == sizeof(int32_t)) {
        int32_t value;
        memcpy(&value, buffer, sizeof(value));
        milliseconds = value;
    } else if (length == 2 * sizeof(int32_t)) {
        int32_t timeval[2];
        memcpy(timeval, buffer, sizeof(timeval));
        if (timeval[0] < 0 || timeval[1] < 0 || timeval[1] >= 1000000)
            mp_raise_OSError(MP_EINVAL);
        milliseconds = (int64_t)timeval[0] * 1000 + ((int64_t)timeval[1] + 999) / 1000;
    } else {
        mp_raise_OSError(MP_EINVAL);
    }
    if (milliseconds < 0 || milliseconds > INT32_MAX) mp_raise_OSError(MP_EINVAL);
    return (mp_int_t)milliseconds;
}

// method socket.setsockopt(level, optname, value)
static mp_obj_t socket_setsockopt(size_t n_args, const mp_obj_t *args) {
    (void)n_args;
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(args[0]);
    if (self->state == MOD_NETWORK_SS_CLOSED) mp_raise_OSError(MP_EBADF);
    if (self->domain != MOD_NETWORK_AF_INET) mp_raise_OSError(MP_EAFNOSUPPORT);

    mp_int_t level = mp_obj_get_int(args[1]);
    mp_int_t opt = mp_obj_get_int(args[2]);
    bool datagram = self->type == MOD_NETWORK_SOCK_DGRAM && (self->proto == 0 || self->proto == 17);
    bool stream = self->type == MOD_NETWORK_SOCK_STREAM && (self->proto == 0 || self->proto == 6);
    bool timeout_option = level == MOD_NETWORK_SOL_SOCKET &&
        (opt == MOD_NETWORK_SO_SNDTIMEO || opt == MOD_NETWORK_SO_RCVTIMEO);
    bool supported =
        ((datagram || stream) && timeout_option) ||
        (datagram && level == MOD_NETWORK_SOL_SOCKET && opt == MOD_NETWORK_SO_BROADCAST) ||
        (stream && level == MPYNN_SOCKET_IPPROTO_TCP && opt == MPYNN_SOCKET_TCP_NODELAY);
    if (!supported) mp_raise_OSError(MP_EOPNOTSUPP);

    const void *optval;
    mp_uint_t optlen;
    mp_int_t val;
    if (mp_obj_is_integer(args[3])) {
        // Timeout integers must not wrap via the legacy boolean-option conversion.
        val = timeout_option ? mp_obj_get_int(args[3]) : mp_obj_get_int_truncated(args[3]);
        if (timeout_option && (val < 0 || val > INT32_MAX)) mp_raise_OSError(MP_EINVAL);
        optval = &val;
        optlen = sizeof(val);
    } else {
        mp_buffer_info_t bufinfo;
        mp_get_buffer_raise(args[3], &bufinfo, MP_BUFFER_READ);
        if (timeout_option) {
            val = socket_timeout_buffer_ms(bufinfo.buf, bufinfo.len);
        } else {
            if (!bufinfo.buf || bufinfo.len != sizeof(mp_int_t)) mp_raise_OSError(MP_EINVAL);
            memcpy(&val, bufinfo.buf, sizeof(val));
        }
        optval = &val;
        optlen = sizeof(val);
    }
    if (!optval || optlen != sizeof(mp_int_t)) mp_raise_OSError(MP_EINVAL);

    if (self->nic == MP_OBJ_NULL) {
        // Only fully validated supported options may lazily select the default NIC.
        uint8_t ip[4] = {0, 0, 0, 0};
        socket_select_nic(self, ip);
    }

    int _errno;
    if (self->nic_protocol->setsockopt(self, level, opt, optval, optlen, &_errno) != 0) {
        mp_raise_OSError(_errno);
    }

    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(socket_setsockopt_obj, 4, 4, socket_setsockopt);

static mp_obj_t socket_makefile(size_t n_args, const mp_obj_t *args) {
    (void)n_args;
    return args[0];
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(socket_makefile_obj, 1, 3, socket_makefile);

// method socket.settimeout(value)
// timeout=0 means non-blocking
// timeout=None means blocking
// otherwise, timeout is in seconds
static mp_obj_t socket_settimeout(mp_obj_t self_in, mp_obj_t timeout_in) {
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(self_in);
    mp_uint_t timeout;
    if (timeout_in == mp_const_none) {
        timeout = -1;
    } else {
        #if MICROPY_PY_BUILTINS_FLOAT
        mp_float_t milliseconds = MICROPY_FLOAT_CONST(1000.0) * mp_obj_get_float(timeout_in);
        // Validate before conversion: negative/NaN/infinite float-to-unsigned
        // conversions are not a valid way to represent a blocking timeout.
        if (!(milliseconds >= 0 && milliseconds < MICROPY_FLOAT_CONST(2147483648.0))) {
            mp_raise_ValueError(MP_ERROR_TEXT("timeout out of range"));
        }
        timeout = (mp_uint_t)milliseconds;
        // Never turn a positive finite timeout into nonblocking mode, and do not
        // expire sooner than requested at the port's millisecond resolution.
        if ((mp_float_t)timeout < milliseconds) ++timeout;
        #else
        mp_int_t seconds = mp_obj_get_int(timeout_in);
        if (seconds < 0 || seconds > 2147483) {
            mp_raise_ValueError(MP_ERROR_TEXT("timeout out of range"));
        }
        timeout = 1000 * (mp_uint_t)seconds;
        #endif
    }
    if (self->nic == MP_OBJ_NULL) {
        #if MICROPY_PY_SOCKET_EXTENDED_STATE
        // store the timeout in the socket state until a NIC is bound
        self->timeout = timeout;
        #else
        // not connected
        mp_raise_OSError(MP_ENOTCONN);
        #endif
    } else {
        int _errno;
        if (self->nic_protocol->settimeout(self, timeout, &_errno) != 0) {
            mp_raise_OSError(_errno);
        }
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(socket_settimeout_obj, socket_settimeout);

static mp_obj_t socket_gettimeout(mp_obj_t self_in) {
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->timeout < 0) return mp_const_none;
    #if MICROPY_PY_BUILTINS_FLOAT
    return mp_obj_new_float((mp_float_t)self->timeout / MICROPY_FLOAT_CONST(1000.0));
    #else
    return mp_obj_new_int(self->timeout / 1000);
    #endif
}
static MP_DEFINE_CONST_FUN_OBJ_1(socket_gettimeout_obj, socket_gettimeout);

// method socket.setblocking(flag)
static mp_obj_t socket_setblocking(mp_obj_t self_in, mp_obj_t blocking) {
    if (mp_obj_is_true(blocking)) {
        return socket_settimeout(self_in, mp_const_none);
    } else {
        return socket_settimeout(self_in, MP_OBJ_NEW_SMALL_INT(0));
    }
}
static MP_DEFINE_CONST_FUN_OBJ_2(socket_setblocking_obj, socket_setblocking);

#ifdef MICROPY_PORT_SOCKET_GETPEERNAME
static mp_obj_t socket_getpeername(mp_obj_t self_in) {
    return MICROPY_PORT_SOCKET_GETPEERNAME(self_in);
}
static MP_DEFINE_CONST_FUN_OBJ_1(socket_getpeername_obj, socket_getpeername);
#endif

#ifdef MICROPY_PORT_SOCKET_GETSOCKNAME
static mp_obj_t socket_getsockname(mp_obj_t self_in) {
    return MICROPY_PORT_SOCKET_GETSOCKNAME(self_in);
}
static MP_DEFINE_CONST_FUN_OBJ_1(socket_getsockname_obj, socket_getsockname);
#endif

#ifdef MICROPY_PORT_SOCKET_SHUTDOWN
static mp_obj_t socket_shutdown(mp_obj_t self_in, mp_obj_t how_in) {
    return MICROPY_PORT_SOCKET_SHUTDOWN(self_in, how_in);
}
static MP_DEFINE_CONST_FUN_OBJ_2(socket_shutdown_obj, socket_shutdown);
#endif

#ifdef MICROPY_PORT_SOCKET_GETSOCKOPT
static mp_obj_t socket_getsockopt(size_t n_args, const mp_obj_t *args) {
    return MICROPY_PORT_SOCKET_GETSOCKOPT(n_args, args);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(socket_getsockopt_obj, 3, 4, socket_getsockopt);
#endif

static const mp_rom_map_elem_t socket_locals_dict_table[] = {
    #ifdef MICROPY_PORT_SOCKET_GETSOCKOPT
    { MP_ROM_QSTR(MP_QSTR_getsockopt), MP_ROM_PTR(&socket_getsockopt_obj) },
    #endif
    #ifdef MICROPY_PORT_SOCKET_SHUTDOWN
    { MP_ROM_QSTR(MP_QSTR_shutdown), MP_ROM_PTR(&socket_shutdown_obj) },
    #endif
    #ifdef MICROPY_PORT_SOCKET_GETSOCKNAME
    { MP_ROM_QSTR(MP_QSTR_getsockname), MP_ROM_PTR(&socket_getsockname_obj) },
    #endif
    #ifdef MICROPY_PORT_SOCKET_GETPEERNAME
    { MP_ROM_QSTR(MP_QSTR_getpeername), MP_ROM_PTR(&socket_getpeername_obj) },
    #endif
    { MP_ROM_QSTR(MP_QSTR___del__), MP_ROM_PTR(&mp_stream_close_obj) },
    { MP_ROM_QSTR(MP_QSTR_close), MP_ROM_PTR(&mp_stream_close_obj) },
    { MP_ROM_QSTR(MP_QSTR_bind), MP_ROM_PTR(&socket_bind_obj) },
    { MP_ROM_QSTR(MP_QSTR_listen), MP_ROM_PTR(&socket_listen_obj) },
    { MP_ROM_QSTR(MP_QSTR_accept), MP_ROM_PTR(&socket_accept_obj) },
    { MP_ROM_QSTR(MP_QSTR_connect), MP_ROM_PTR(&socket_connect_obj) },
    { MP_ROM_QSTR(MP_QSTR_send), MP_ROM_PTR(&socket_send_obj) },
    { MP_ROM_QSTR(MP_QSTR_sendall), MP_ROM_PTR(&socket_sendall_obj) },
    { MP_ROM_QSTR(MP_QSTR_recv), MP_ROM_PTR(&socket_recv_obj) },
    { MP_ROM_QSTR(MP_QSTR_sendto), MP_ROM_PTR(&socket_sendto_obj) },
    { MP_ROM_QSTR(MP_QSTR_recvfrom), MP_ROM_PTR(&socket_recvfrom_obj) },
    { MP_ROM_QSTR(MP_QSTR_recv_into), MP_ROM_PTR(&socket_recv_into_obj) },
    { MP_ROM_QSTR(MP_QSTR_recvfrom_into), MP_ROM_PTR(&socket_recvfrom_into_obj) },
    { MP_ROM_QSTR(MP_QSTR_setsockopt), MP_ROM_PTR(&socket_setsockopt_obj) },
    { MP_ROM_QSTR(MP_QSTR_makefile), MP_ROM_PTR(&socket_makefile_obj) },
    { MP_ROM_QSTR(MP_QSTR_settimeout), MP_ROM_PTR(&socket_settimeout_obj) },
    { MP_ROM_QSTR(MP_QSTR_gettimeout), MP_ROM_PTR(&socket_gettimeout_obj) },
    { MP_ROM_QSTR(MP_QSTR_setblocking), MP_ROM_PTR(&socket_setblocking_obj) },

    { MP_ROM_QSTR(MP_QSTR_read), MP_ROM_PTR(&mp_stream_read_obj) },
    { MP_ROM_QSTR(MP_QSTR_readinto), MP_ROM_PTR(&mp_stream_readinto_obj) },
    { MP_ROM_QSTR(MP_QSTR_readline), MP_ROM_PTR(&mp_stream_unbuffered_readline_obj) },
    { MP_ROM_QSTR(MP_QSTR_write), MP_ROM_PTR(&mp_stream_write_obj) },
};

static MP_DEFINE_CONST_DICT(socket_locals_dict, socket_locals_dict_table);

static mp_uint_t socket_read(mp_obj_t self_in, void *buf, mp_uint_t size, int *errcode) {
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->nic == MP_OBJ_NULL) {
        *errcode = self->state == MOD_NETWORK_SS_CLOSED ? MP_EBADF : MP_ENOTCONN;
        return MP_STREAM_ERROR;
    }
    mp_int_t ret = self->nic_protocol->recv(self, (byte *)buf, size, errcode);
    if (ret < 0) {
        ret = MP_STREAM_ERROR;
    }
    return ret;
}

static mp_uint_t socket_write(mp_obj_t self_in, const void *buf, mp_uint_t size, int *errcode) {
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (self->nic == MP_OBJ_NULL) {
        *errcode = self->state == MOD_NETWORK_SS_CLOSED ? MP_EBADF : MP_ENOTCONN;
        return MP_STREAM_ERROR;
    }
    mp_int_t ret = self->nic_protocol->send(self, buf, size, errcode);
    if (ret < 0) {
        ret = MP_STREAM_ERROR;
    }
    return ret;
}

static mp_uint_t socket_ioctl(mp_obj_t self_in, mp_uint_t request, uintptr_t arg, int *errcode) {
    mod_network_socket_obj_t *self = MP_OBJ_TO_PTR(self_in);
    if (request == MP_STREAM_CLOSE) {
        if (self->nic != MP_OBJ_NULL) {
            self->nic_protocol->close(self);
            self->nic = MP_OBJ_NULL;
        }
        self->state = MOD_NETWORK_SS_CLOSED;
        return 0;
    }
    if (self->nic == MP_OBJ_NULL) {
        if (request == MP_STREAM_POLL) {
            if (self->state == MOD_NETWORK_SS_NEW) {
                // New sockets are writable and not connected.
                return MP_STREAM_POLL_HUP | MP_STREAM_POLL_WR;
            } else if (self->state == MOD_NETWORK_SS_CLOSED) {
                // Closed socket, return invalid.
                return MP_STREAM_POLL_NVAL;
            }
        }
        *errcode = MP_EINVAL;
        return MP_STREAM_ERROR;
    }
    return self->nic_protocol->ioctl(self, request, arg, errcode);
}

static const mp_stream_p_t socket_stream_p = {
    .read = socket_read,
    .write = socket_write,
    .ioctl = socket_ioctl,
    .is_text = false,
};

static MP_DEFINE_CONST_OBJ_TYPE(
    socket_type,
    MP_QSTR_socket,
    MP_TYPE_FLAG_NONE,
    make_new, socket_make_new,
    protocol, &socket_stream_p,
    locals_dict, &socket_locals_dict,
    print, socket_print
    );

/******************************************************************************/
// socket module

// Parse only complete dotted-decimal literals, never truncated prefixes. Keep
// caller output intact on failure so DNS/error paths cannot expose partial octets.
static bool socket_parse_ipv4_literal(const char *text, size_t length, uint8_t out[4]) {
    size_t position = 0;
    uint8_t parsed[4];
    for (unsigned group = 0; group < 4; ++group) {
        unsigned octet = 0, digits = 0;
        while (position < length && text[position] >= '0' && text[position] <= '9') {
            octet = octet * 10 + (unsigned)(text[position++] - '0');
            if (++digits > 3 || octet > 255) return false;
        }
        if (!digits || (group < 3 ? position == length || text[position++] != '.' : position != length))
            return false;
        parsed[group] = (uint8_t)octet;
    }
    memcpy(out, parsed, sizeof(parsed));
    return true;
}

// function socket.getaddrinfo(host, port)
static mp_obj_t mod_socket_getaddrinfo(size_t n_args, const mp_obj_t *args) {
    if (args[0] == mp_const_none && args[1] == mp_const_none)
        mp_raise_ValueError(MP_ERROR_TEXT("host and port cannot both be None"));
    size_t hlen = 0;
    const char *host = args[0] == mp_const_none ? NULL : mp_obj_str_get_data(args[0], &hlen);
    mp_int_t port = 0;
    mp_int_t service_proto = 0;
    if (mp_obj_is_str(args[1])) {
        size_t service_len;
        const char *service = mp_obj_str_get_data(args[1], &service_len);
        bool decimal = service_len > 0;
        for (size_t i = 0; i < service_len; ++i) {
            if (service[i] == '\0') mp_raise_ValueError(MP_ERROR_TEXT("embedded NUL in service"));
            if (service[i] < '0' || service[i] > '9') decimal = false;
        }
        if (decimal) {
            for (size_t i = 0; i < service_len; ++i) {
                // Bound each step so arbitrarily long decimal strings cannot overflow.
                port = port * 10 + service[i] - '0';
                if (port > 65535) mp_raise_ValueError(MP_ERROR_TEXT("port out of range"));
            }
        } else {
            // Port-owned, case-sensitive services only: no filesystem/network lookup
            // or transport ambiguity (including domain, which is strictly UDP).
            static const struct {
                const char *name;
                uint16_t port;
                uint8_t proto;
            } services[] = {
                {"http", 80, 6}, {"https", 443, 6}, {"ntp", 123, 17},
                {"domain", 53, 17}, {"ssh", 22, 6}, {"telnet", 23, 6}, {"ftp", 21, 6},
            };
            for (size_t i = 0; i < sizeof(services) / sizeof(services[0]); ++i) {
                if (service_len == strlen(services[i].name)
                    && memcmp(service, services[i].name, service_len) == 0) {
                    port = services[i].port;
                    service_proto = services[i].proto;
                    break;
                }
            }
            // This internal socket module has no EAI_SERVICE; unknown services use
            // EOPNOTSUPP, as do service/transport conflicts below.
            if (service_proto == 0) mp_raise_OSError(MP_EOPNOTSUPP);
        }
    } else if (args[1] != mp_const_none) {
        // None means no service (port zero); integer conversion stays unchanged.
        port = mp_obj_get_int(args[1]);
    }
    uint8_t out_ip[MOD_NETWORK_IPADDR_BUF_SIZE];
    bool have_ip = false;

    if (port < 0 || port > 65535) mp_raise_ValueError(MP_ERROR_TEXT("port out of range"));
    for (size_t i = 0; i < hlen; ++i) {
        if (host[i] == '\0') mp_raise_ValueError(MP_ERROR_TEXT("embedded NUL in host"));
    }
    mp_int_t family = n_args > 2 ? mp_obj_get_int(args[2]) : 0;
    mp_int_t type = n_args > 3 ? mp_obj_get_int(args[3]) : 0;
    mp_int_t proto = n_args > 4 ? mp_obj_get_int(args[4]) : 0;
    mp_int_t flags = n_args > 5 ? mp_obj_get_int(args[5]) : 0;
    if (family != 0 && family != MOD_NETWORK_AF_INET) mp_raise_OSError(MP_EAFNOSUPPORT);
    if ((type != 0 && type != MOD_NETWORK_SOCK_STREAM && type != MOD_NETWORK_SOCK_DGRAM)
        || (proto != 0 && proto != 6 && proto != 17)
        || (flags & ~(MPYNN_SOCKET_AI_PASSIVE | MPYNN_SOCKET_AI_NUMERICHOST |
                      MPYNN_SOCKET_AI_NUMERICSERV)) != 0) mp_raise_OSError(MP_EOPNOTSUPP);
    if (service_proto != 0) {
        if (flags & MPYNN_SOCKET_AI_NUMERICSERV) mp_raise_OSError(MP_EOPNOTSUPP);
        mp_int_t service_type = service_proto == 17 ? MOD_NETWORK_SOCK_DGRAM : MOD_NETWORK_SOCK_STREAM;
        if ((type != 0 && type != service_type) || (proto != 0 && proto != service_proto)) {
            mp_raise_OSError(MP_EOPNOTSUPP);
        }
        type = service_type;
        proto = service_proto;
    }
    if (type == 0) type = proto == 17 ? MOD_NETWORK_SOCK_DGRAM : MOD_NETWORK_SOCK_STREAM;
    if (proto == 0) proto = type == MOD_NETWORK_SOCK_DGRAM ? 17 : 6;
    if ((type == MOD_NETWORK_SOCK_STREAM && proto != 6)
        || (type == MOD_NETWORK_SOCK_DGRAM && proto != 17)) mp_raise_OSError(MP_EOPNOTSUPP);

    if (host == NULL) {
        // Local bind target when passive, otherwise IPv4 loopback target.
        // This is address selection only; Circle does not implement loopback routing.
        out_ip[0] = (flags & MPYNN_SOCKET_AI_PASSIVE) ? 0 : 127;
        out_ip[1] = 0;
        out_ip[2] = 0;
        out_ip[3] = (flags & MPYNN_SOCKET_AI_PASSIVE) ? 0 : 1;
        have_ip = true;
    } else if (hlen > 0) {
        have_ip = socket_parse_ipv4_literal(host, hlen, out_ip);
        if (!have_ip) {
            // Malformed numeric literals cannot wrap/truncate into another host.
            // Names containing letters go to DNS intact, including numeric prefixes.
            bool numeric = true;
            for (size_t i = 0; i < hlen; ++i) {
                if (host[i] != '.' && (host[i] < '0' || host[i] > '9')) {
                    numeric = false;
                    break;
                }
            }
            if (numeric) mp_raise_OSError(MP_EINVAL);
        }
    }

    if (!have_ip && (flags & MPYNN_SOCKET_AI_NUMERICHOST)) mp_raise_OSError(MP_EINVAL);
    if (!have_ip) {
        // find a NIC that can do a name lookup
        for (mp_uint_t i = 0; i < MP_STATE_PORT(mod_network_nic_list).len; i++) {
            mp_obj_t nic = MP_STATE_PORT(mod_network_nic_list).items[i];
            mod_network_nic_protocol_t *nic_protocol = (mod_network_nic_protocol_t *)MP_OBJ_TYPE_GET_SLOT(mp_obj_get_type(nic), protocol);
            if (nic_protocol->gethostbyname != NULL) {
                int ret = nic_protocol->gethostbyname(nic, host, hlen, out_ip);
                if (ret != 0) {
                    mp_raise_OSError(ret);
                }
                have_ip = true;
                break;
            }
        }
    }

    if (!have_ip) {
        mp_raise_msg(&mp_type_OSError, MP_ERROR_TEXT("no available NIC"));
    }

    mp_obj_tuple_t *tuple = MP_OBJ_TO_PTR(mp_obj_new_tuple(5, NULL));
    tuple->items[0] = MP_OBJ_NEW_SMALL_INT(MOD_NETWORK_AF_INET);
    tuple->items[1] = MP_OBJ_NEW_SMALL_INT(type);
    tuple->items[2] = MP_OBJ_NEW_SMALL_INT(proto);
    tuple->items[3] = MP_OBJ_NEW_QSTR(MP_QSTR_);
    tuple->items[4] = netutils_format_inet_addr(out_ip, port, NETUTILS_BIG);
    return mp_obj_new_list(1, (mp_obj_t *)&tuple);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(mod_socket_getaddrinfo_obj, 2, 6, mod_socket_getaddrinfo);

static const mp_rom_map_elem_t mp_module_socket_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_socket) },

    { MP_ROM_QSTR(MP_QSTR_socket), MP_ROM_PTR(&socket_type) },
    { MP_ROM_QSTR(MP_QSTR_getaddrinfo), MP_ROM_PTR(&mod_socket_getaddrinfo_obj) },

    #ifdef MICROPY_PORT_SOCKET_SHUTDOWN
    { MP_ROM_QSTR(MP_QSTR_SHUT_RD), MP_ROM_INT(0) },
    { MP_ROM_QSTR(MP_QSTR_SHUT_WR), MP_ROM_INT(1) },
    { MP_ROM_QSTR(MP_QSTR_SHUT_RDWR), MP_ROM_INT(2) },
    #endif

    // class constants
    { MP_ROM_QSTR(MP_QSTR_AF_INET), MP_ROM_INT(MOD_NETWORK_AF_INET) },
    { MP_ROM_QSTR(MP_QSTR_AF_INET6), MP_ROM_INT(MOD_NETWORK_AF_INET6) },
    // Port-owned IPv4 resolver flags; unsupported bits are rejected explicitly.
    { MP_ROM_QSTR(MP_QSTR_AI_PASSIVE), MP_ROM_INT(MPYNN_SOCKET_AI_PASSIVE) },
    { MP_ROM_QSTR(MP_QSTR_AI_NUMERICHOST), MP_ROM_INT(MPYNN_SOCKET_AI_NUMERICHOST) },
    { MP_ROM_QSTR(MP_QSTR_AI_NUMERICSERV), MP_ROM_INT(MPYNN_SOCKET_AI_NUMERICSERV) },

    { MP_ROM_QSTR(MP_QSTR_SOCK_STREAM), MP_ROM_INT(MOD_NETWORK_SOCK_STREAM) },
    { MP_ROM_QSTR(MP_QSTR_SOCK_DGRAM), MP_ROM_INT(MOD_NETWORK_SOCK_DGRAM) },
    { MP_ROM_QSTR(MP_QSTR_SOCK_RAW), MP_ROM_INT(MOD_NETWORK_SOCK_RAW) },

    { MP_ROM_QSTR(MP_QSTR_SOL_SOCKET), MP_ROM_INT(MOD_NETWORK_SOL_SOCKET) },
    { MP_ROM_QSTR(MP_QSTR_SO_REUSEADDR), MP_ROM_INT(MOD_NETWORK_SO_REUSEADDR) },
    { MP_ROM_QSTR(MP_QSTR_SO_BROADCAST), MP_ROM_INT(MOD_NETWORK_SO_BROADCAST) },
    #ifdef MICROPY_PORT_SOCKET_GETSOCKOPT
    { MP_ROM_QSTR(MP_QSTR_SO_ERROR), MP_ROM_INT(MPYNN_SOCKET_SO_ERROR) },
    { MP_ROM_QSTR(MP_QSTR_SO_TYPE), MP_ROM_INT(MPYNN_SOCKET_SO_TYPE) },
    { MP_ROM_QSTR(MP_QSTR_IPPROTO_TCP), MP_ROM_INT(MPYNN_SOCKET_IPPROTO_TCP) },
    { MP_ROM_QSTR(MP_QSTR_TCP_NODELAY), MP_ROM_INT(MPYNN_SOCKET_TCP_NODELAY) },
    #endif
    { MP_ROM_QSTR(MP_QSTR_SO_KEEPALIVE), MP_ROM_INT(MOD_NETWORK_SO_KEEPALIVE) },
    { MP_ROM_QSTR(MP_QSTR_SO_SNDTIMEO), MP_ROM_INT(MOD_NETWORK_SO_SNDTIMEO) },
    { MP_ROM_QSTR(MP_QSTR_SO_RCVTIMEO), MP_ROM_INT(MOD_NETWORK_SO_RCVTIMEO) },

    /*
    { MP_ROM_QSTR(MP_QSTR_IPPROTO_IP), MP_ROM_INT(MOD_NETWORK_IPPROTO_IP) },
    { MP_ROM_QSTR(MP_QSTR_IPPROTO_ICMP), MP_ROM_INT(MOD_NETWORK_IPPROTO_ICMP) },
    { MP_ROM_QSTR(MP_QSTR_IPPROTO_IPV4), MP_ROM_INT(MOD_NETWORK_IPPROTO_IPV4) },
    { MP_ROM_QSTR(MP_QSTR_IPPROTO_TCP), MP_ROM_INT(MOD_NETWORK_IPPROTO_TCP) },
    { MP_ROM_QSTR(MP_QSTR_IPPROTO_UDP), MP_ROM_INT(MOD_NETWORK_IPPROTO_UDP) },
    { MP_ROM_QSTR(MP_QSTR_IPPROTO_IPV6), MP_ROM_INT(MOD_NETWORK_IPPROTO_IPV6) },
    { MP_ROM_QSTR(MP_QSTR_IPPROTO_RAW), MP_ROM_INT(MOD_NETWORK_IPPROTO_RAW) },
    */
};

static MP_DEFINE_CONST_DICT(mp_module_socket_globals, mp_module_socket_globals_table);

const mp_obj_module_t mp_module_socket = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&mp_module_socket_globals,
};

MP_REGISTER_EXTENSIBLE_MODULE(MP_QSTR_socket, mp_module_socket);

#endif // MICROPY_PY_NETWORK && MICROPY_PY_SOCKET && !MICROPY_PY_LWIP

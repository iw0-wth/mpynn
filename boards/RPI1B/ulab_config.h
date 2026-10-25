// SPDX-License-Identifier: MIT
#ifndef MPYNN_RPI1B_ULAB_CONFIG_H
#define MPYNN_RPI1B_ULAB_CONFIG_H

// Match OpenMV's four-dimensional ndarray ABI. Keep the full upstream 6.12.0
// feature defaults in modules/ulab/code/ulab.h, including complex, scipy,
// arithmetic, frombuffer, zeros, roll, reshape, and min/max reductions.
// Upstream intentionally disables unfinished curve_fit and the user example;
// do not enable those placeholders or replace any array operation in Python.
#define ULAB_MAX_DIMS (4)

#endif // MPYNN_RPI1B_ULAB_CONFIG_H

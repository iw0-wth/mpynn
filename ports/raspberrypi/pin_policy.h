// SPDX-License-Identifier: MIT
#ifndef MPYNN_PIN_POLICY_H
#define MPYNN_PIN_POLICY_H

/* P1 only: Raspberry Pi Model B 26-pin connector, NOT the 40-pin header.
 * Revision changes verified against Eben Upton's 2012-09-05 announcement:
 * https://www.raspberrypi.com/news/upcoming-board-revision/
 * P1 physical 3/5/13: Rev1 BCM0/1/21; Rev2 BCM2/3/27.
 * P5, ACT LED, camera, audio and every other non-P1 GPIO remain private.
 * These enums intentionally do not depend on Circle's enum numbering.
 */
enum mpynn_pin_board {
    MPYNN_PIN_BOARD_UNKNOWN = 0,
    MPYNN_PIN_BOARD_B_REV1 = 1,
    MPYNN_PIN_BOARD_B_REV2 = 2
};

static inline int mpynn_pin_header_gpio(enum mpynn_pin_board board, int physical) {
    if (board != MPYNN_PIN_BOARD_B_REV1 && board != MPYNN_PIN_BOARD_B_REV2) {
        return -1;
    }
    switch (physical) {
        case 3: return board == MPYNN_PIN_BOARD_B_REV1 ? 0 : 2;
        case 5: return board == MPYNN_PIN_BOARD_B_REV1 ? 1 : 3;
        case 7: return 4;
        case 8: return 14;
        case 10: return 15;
        case 11: return 17;
        case 12: return 18;
        case 13: return board == MPYNN_PIN_BOARD_B_REV1 ? 21 : 27;
        case 15: return 22;
        case 16: return 23;
        case 18: return 24;
        case 19: return 10;
        case 21: return 9;
        case 22: return 25;
        case 23: return 11;
        case 24: return 8;
        case 26: return 7;
        default: return -1;
    }
}

static inline int mpynn_pin_is_visible(enum mpynn_pin_board board, int bcm) {
    if (bcm < 0 || bcm >= 32) {
        return 0;
    }
    for (int p = 1; p <= 26; ++p) {
        if (mpynn_pin_header_gpio(board, p) == bcm) {
            return 1;
        }
    }
    return 0;
}

static inline int mpynn_pin_is_console(int bcm) {
    return bcm == 14 || bcm == 15;
}

static inline int mpynn_pin_is_allowed(enum mpynn_pin_board board, int bcm) {
    return mpynn_pin_is_visible(board, bcm) && !mpynn_pin_is_console(bcm);
}
#endif

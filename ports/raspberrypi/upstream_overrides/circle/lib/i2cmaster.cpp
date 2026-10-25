//
// i2cmaster.cpp
//
// Circle - A C++ bare metal environment for Raspberry Pi
// Copyright (C) 2014-2023  R. Stange <rsta2@o2online.de>
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
#include <circle/i2cmaster.h>
#include <circle/memio.h>
#include <circle/bcm2835.h>
#include <circle/machineinfo.h>
#include <circle/synchronize.h>
#include <circle/timer.h>
#include <assert.h>

#if RASPPI < 4
#define DEVICES 2
#else
#define DEVICES 7
#endif

#define CONFIGS 3
#define GPIOS 2
#define GPIO_SDA 0
#define GPIO_SCL 1

#define C_I2CEN (1 << 15)
#define C_INTR  (1 << 10)
#define C_INTT  (1 << 9)
#define C_INTD  (1 << 8)
#define C_ST    (1 << 7)
#define C_CLEAR (1 << 5)
#define C_READ  (1 << 0)

#define S_CLKT (1 << 9)
#define S_ERR  (1 << 8)
#define S_RXF  (1 << 7)
#define S_TXE  (1 << 6)
#define S_RXD  (1 << 5)
#define S_TXD  (1 << 4)
#define S_RXR  (1 << 3)
#define S_TXW  (1 << 2)
#define S_DONE (1 << 1)
#define S_TA   (1 << 0)

#define FIFO__MASK 0xFF
#define FIFO_SIZE 16

static uintptr s_BaseAddress[DEVICES] =
{
    ARM_IO_BASE + 0x205000,
    ARM_IO_BASE + 0x804000,
#if RASPPI >= 4
    0,
    ARM_IO_BASE + 0x205600,
    ARM_IO_BASE + 0x205800,
    ARM_IO_BASE + 0x205A80,
    ARM_IO_BASE + 0x205C00
#endif
};

#define NONE {10000, 10000}

static unsigned s_GPIOConfig[DEVICES][CONFIGS][GPIOS] =
{
    {{ 0,  1}, {28, 29}, {44, 45}},
    {{ 2,  3},   NONE,     NONE  },
#if RASPPI >= 4
    {  NONE,     NONE,     NONE  },
    {{ 2,  3}, { 4,  5},   NONE  },
    {{ 6,  7}, { 8,  9},   NONE  },
    {{10, 11}, {12, 13},   NONE  },
    {{22, 23},   NONE,     NONE  }
#endif
};

#define ALT_FUNC(device, config) ((device) == 0 && (config) == 2 \
                                  ? GPIOModeAlternateFunction1 \
                                  : ((device) < 2 \
                                     ? GPIOModeAlternateFunction0 \
                                     : GPIOModeAlternateFunction5))

static boolean DeadlineExpired (u64 nDeadline)
{
    return CTimer::GetClockTicks64 () >= nDeadline;
}

static void TransferCleanup (uintptr nBaseAddress)
{
    write32 (nBaseAddress + ARM_BSC_C__OFFSET, C_CLEAR);
    write32 (nBaseAddress + ARM_BSC_S__OFFSET, S_DONE);
}

CI2CMaster::CI2CMaster (unsigned nDevice, boolean bFastMode, unsigned nConfig)
:   m_nDevice (nDevice),
    m_nBaseAddress (0),
    m_bFastMode (bFastMode),
    m_nConfig (nConfig),
    m_bValid (FALSE),
    m_nCoreClockRate (CMachineInfo::Get ()->GetClockRate (CLOCK_ID_CORE)),
    m_nClockSpeed (0),
    m_SpinLock (TASK_LEVEL)
{
    // Validate the complete mapping before touching either GPIO mux.
    if (nDevice >= DEVICES || nConfig >= CONFIGS
        || s_GPIOConfig[nDevice][nConfig][GPIO_SDA] >= GPIO_PINS
        || s_GPIOConfig[nDevice][nConfig][GPIO_SCL] >= GPIO_PINS
        || s_BaseAddress[nDevice] == 0)
    {
        return;
    }

    m_nBaseAddress = s_BaseAddress[nDevice];
    assert (m_nBaseAddress != 0);

    m_SDA.AssignPin (s_GPIOConfig[nDevice][nConfig][GPIO_SDA]);
    m_SDA.SetMode (ALT_FUNC (nDevice, nConfig));
    m_SDA.SetPullMode (GPIOPullModeUp);

    m_SCL.AssignPin (s_GPIOConfig[nDevice][nConfig][GPIO_SCL]);
    m_SCL.SetMode (ALT_FUNC (nDevice, nConfig));
    m_SCL.SetPullMode (GPIOPullModeUp);

    assert (m_nCoreClockRate > 0);
    m_bValid = TRUE;
}

CI2CMaster::~CI2CMaster (void)
{
    if (m_bValid)
    {
        m_SDA.SetMode (GPIOModeInput);
        m_SCL.SetMode (GPIOModeInput);
        m_bValid = FALSE;
    }
    m_nBaseAddress = 0;
}

boolean CI2CMaster::Initialize (void)
{
    if (!m_bValid)
    {
        return FALSE;
    }
    SetClock (m_bFastMode ? 400000 : 100000);
    return TRUE;
}

void CI2CMaster::SetClock (unsigned nClockSpeed)
{
    assert (m_bValid);
    PeripheralEntry ();
    assert (nClockSpeed > 0);
    m_nClockSpeed = nClockSpeed;
    u16 nDivider = (u16) (m_nCoreClockRate / nClockSpeed);
    write32 (m_nBaseAddress + ARM_BSC_DIV__OFFSET, nDivider);
    PeripheralExit ();
}

int CI2CMaster::Read (u8 ucAddress, void *pBuffer, unsigned nCount)
{
    assert (m_bValid);
    if (ucAddress >= 0x80 || nCount == 0 || pBuffer == 0)
    {
        return -I2C_MASTER_INALID_PARM;
    }

    m_SpinLock.Acquire ();
    u8 *pData = (u8 *) pBuffer;
    unsigned nRemaining = nCount;
    int nResult = 0;
    boolean bTimedOut = FALSE;
    const u64 nDeadline = CTimer::GetClockTicks64 () + I2C_MASTER_TRANSFER_TIMEOUT_US;

    PeripheralEntry ();
    write32 (m_nBaseAddress + ARM_BSC_A__OFFSET, ucAddress);
    write32 (m_nBaseAddress + ARM_BSC_C__OFFSET, C_CLEAR);
    write32 (m_nBaseAddress + ARM_BSC_S__OFFSET, S_CLKT | S_ERR | S_DONE);
    write32 (m_nBaseAddress + ARM_BSC_DLEN__OFFSET, nCount);
    write32 (m_nBaseAddress + ARM_BSC_C__OFFSET, C_I2CEN | C_ST | C_READ);

    for (;;)
    {
        u32 nStatus = read32 (m_nBaseAddress + ARM_BSC_S__OFFSET);
        if (nStatus & S_DONE)
        {
            break;
        }
        if (DeadlineExpired (nDeadline))
        {
            bTimedOut = TRUE;
            break;
        }
        while (nRemaining > 0 && (nStatus & S_RXD))
        {
            *pData++ = read32 (m_nBaseAddress + ARM_BSC_FIFO__OFFSET) & FIFO__MASK;
            --nRemaining;
            ++nResult;
            nStatus = read32 (m_nBaseAddress + ARM_BSC_S__OFFSET);
            if (nStatus & S_DONE)
            {
                break;
            }
            if (DeadlineExpired (nDeadline))
            {
                bTimedOut = TRUE;
                break;
            }
        }
        if (bTimedOut)
        {
            break;
        }
    }

    if (!bTimedOut)
    {
        while (nRemaining > 0)
        {
            if (DeadlineExpired (nDeadline))
            {
                bTimedOut = TRUE;
                break;
            }
            u32 nStatus = read32 (m_nBaseAddress + ARM_BSC_S__OFFSET);
            if (!(nStatus & S_RXD))
            {
                break;
            }
            *pData++ = read32 (m_nBaseAddress + ARM_BSC_FIFO__OFFSET) & FIFO__MASK;
            --nRemaining;
            ++nResult;
            if (DeadlineExpired (nDeadline))
            {
                bTimedOut = TRUE;
                break;
            }
        }
    }

    u32 nStatus = read32 (m_nBaseAddress + ARM_BSC_S__OFFSET);
    if (bTimedOut)
    {
        TransferCleanup (m_nBaseAddress);
        nResult = -I2C_MASTER_TIMEOUT;
    }
    else if (nStatus & S_ERR)
    {
        write32 (m_nBaseAddress + ARM_BSC_S__OFFSET, S_ERR);
        nResult = -I2C_MASTER_ERROR_NACK;
    }
    else if (nStatus & S_CLKT)
    {
        nResult = -I2C_MASTER_ERROR_CLKT;
    }
    else if (nRemaining > 0)
    {
        nResult = -I2C_MASTER_DATA_LEFT;
    }
    write32 (m_nBaseAddress + ARM_BSC_S__OFFSET, S_DONE);
    PeripheralExit ();
    m_SpinLock.Release ();
    return nResult;
}

int CI2CMaster::Write (u8 ucAddress, const void *pBuffer, unsigned nCount)
{
    assert (m_bValid);
    if (ucAddress >= 0x80 || (nCount != 0 && pBuffer == 0))
    {
        return -I2C_MASTER_INALID_PARM;
    }

    m_SpinLock.Acquire ();
    const u8 *pData = (const u8 *) pBuffer;
    unsigned nRemaining = nCount;
    int nResult = 0;
    boolean bTimedOut = FALSE;
    const u64 nDeadline = CTimer::GetClockTicks64 () + I2C_MASTER_TRANSFER_TIMEOUT_US;

    PeripheralEntry ();
    write32 (m_nBaseAddress + ARM_BSC_A__OFFSET, ucAddress);
    write32 (m_nBaseAddress + ARM_BSC_C__OFFSET, C_CLEAR);
    write32 (m_nBaseAddress + ARM_BSC_S__OFFSET, S_CLKT | S_ERR | S_DONE);
    write32 (m_nBaseAddress + ARM_BSC_DLEN__OFFSET, nCount);

    for (unsigned i = 0; nRemaining > 0 && i < FIFO_SIZE; ++i)
    {
        write32 (m_nBaseAddress + ARM_BSC_FIFO__OFFSET, *pData++);
        --nRemaining;
        ++nResult;
    }
    write32 (m_nBaseAddress + ARM_BSC_C__OFFSET, C_I2CEN | C_ST);

    for (;;)
    {
        u32 nStatus = read32 (m_nBaseAddress + ARM_BSC_S__OFFSET);
        if (nStatus & S_DONE)
        {
            break;
        }
        if (DeadlineExpired (nDeadline))
        {
            bTimedOut = TRUE;
            break;
        }
        while (nRemaining > 0 && (nStatus & S_TXD))
        {
            write32 (m_nBaseAddress + ARM_BSC_FIFO__OFFSET, *pData++);
            --nRemaining;
            ++nResult;
            nStatus = read32 (m_nBaseAddress + ARM_BSC_S__OFFSET);
            if (nStatus & S_DONE)
            {
                break;
            }
            if (DeadlineExpired (nDeadline))
            {
                bTimedOut = TRUE;
                break;
            }
        }
        if (bTimedOut)
        {
            break;
        }
    }

    u32 nStatus = read32 (m_nBaseAddress + ARM_BSC_S__OFFSET);
    if (bTimedOut)
    {
        TransferCleanup (m_nBaseAddress);
        nResult = -I2C_MASTER_TIMEOUT;
    }
    else if (nStatus & S_ERR)
    {
        write32 (m_nBaseAddress + ARM_BSC_S__OFFSET, S_ERR);
        nResult = -I2C_MASTER_ERROR_NACK;
    }
    else if (nStatus & S_CLKT)
    {
        nResult = -I2C_MASTER_ERROR_CLKT;
    }
    else if (nRemaining > 0)
    {
        nResult = -I2C_MASTER_DATA_LEFT;
    }
    write32 (m_nBaseAddress + ARM_BSC_S__OFFSET, S_DONE);
    PeripheralExit ();
    m_SpinLock.Release ();
    return nResult;
}

int CI2CMaster::WriteReadRepeatedStart (u8 ucAddress,
                                        const void *pWriteBuffer, unsigned nWriteCount,
                                        void *pReadBuffer, unsigned nReadCount)
{
    assert (m_bValid);
    if (ucAddress >= 0x80 || nWriteCount == 0 || nWriteCount > FIFO_SIZE
        || pWriteBuffer == 0 || nReadCount == 0 || pReadBuffer == 0)
    {
        return -I2C_MASTER_INALID_PARM;
    }

    m_SpinLock.Acquire ();
    const u8 *pWriteData = (const u8 *) pWriteBuffer;
    u8 *pReadData = (u8 *) pReadBuffer;
    unsigned nRemaining = nReadCount;
    int nResult = 0;
    boolean bTimedOut = FALSE;
    const u64 nDeadline = CTimer::GetClockTicks64 () + I2C_MASTER_TRANSFER_TIMEOUT_US;

    PeripheralEntry ();
    write32 (m_nBaseAddress + ARM_BSC_A__OFFSET, ucAddress);
    write32 (m_nBaseAddress + ARM_BSC_C__OFFSET, C_CLEAR);
    write32 (m_nBaseAddress + ARM_BSC_S__OFFSET, S_CLKT | S_ERR | S_DONE);
    write32 (m_nBaseAddress + ARM_BSC_DLEN__OFFSET, nWriteCount);
    for (unsigned i = 0; i < nWriteCount; ++i)
    {
        write32 (m_nBaseAddress + ARM_BSC_FIFO__OFFSET, *pWriteData++);
    }
    write32 (m_nBaseAddress + ARM_BSC_C__OFFSET, C_I2CEN | C_ST);

    // Wait for the write phase to become active, but do not spin forever.
    for (;;)
    {
        u32 nStatus = read32 (m_nBaseAddress + ARM_BSC_S__OFFSET);
        if ((nStatus & S_TA) || (nStatus & S_DONE))
        {
            break;
        }
        if (DeadlineExpired (nDeadline))
        {
            bTimedOut = TRUE;
            break;
        }
    }

    if (!bTimedOut)
    {
        write32 (m_nBaseAddress + ARM_BSC_DLEN__OFFSET, nReadCount);
        write32 (m_nBaseAddress + ARM_BSC_C__OFFSET, C_I2CEN | C_ST | C_READ);

        for (;;)
        {
            u32 nStatus = read32 (m_nBaseAddress + ARM_BSC_S__OFFSET);
            if (nStatus & S_DONE)
            {
                break;
            }
            if (DeadlineExpired (nDeadline))
            {
                bTimedOut = TRUE;
                break;
            }
            // Never consume more bytes than the caller's read buffer, even
            // when the status register remains RXD after the requested count.
            while (nRemaining > 0 && (nStatus & S_RXD))
            {
                *pReadData++ = read32 (m_nBaseAddress + ARM_BSC_FIFO__OFFSET) & FIFO__MASK;
                --nRemaining;
                ++nResult;
                nStatus = read32 (m_nBaseAddress + ARM_BSC_S__OFFSET);
                if (nStatus & S_DONE)
                {
                    break;
                }
                if (DeadlineExpired (nDeadline))
                {
                    bTimedOut = TRUE;
                    break;
                }
            }
            if (bTimedOut)
            {
                break;
            }
        }

        if (!bTimedOut)
        {
            while (nRemaining > 0)
            {
                u32 nStatus = read32 (m_nBaseAddress + ARM_BSC_S__OFFSET);
                if (!(nStatus & S_RXD))
                {
                    break;
                }
                *pReadData++ = read32 (m_nBaseAddress + ARM_BSC_FIFO__OFFSET) & FIFO__MASK;
                --nRemaining;
                ++nResult;
                if (DeadlineExpired (nDeadline))
                {
                    bTimedOut = TRUE;
                    break;
                }
            }
        }
    }

    u32 nStatus = read32 (m_nBaseAddress + ARM_BSC_S__OFFSET);
    if (bTimedOut)
    {
        TransferCleanup (m_nBaseAddress);
        nResult = -I2C_MASTER_TIMEOUT;
    }
    else if (nStatus & S_ERR)
    {
        write32 (m_nBaseAddress + ARM_BSC_S__OFFSET, S_ERR);
        nResult = -I2C_MASTER_ERROR_NACK;
    }
    else if (nStatus & S_CLKT)
    {
        nResult = -I2C_MASTER_ERROR_CLKT;
    }
    else if (nRemaining > 0)
    {
        nResult = -I2C_MASTER_DATA_LEFT;
    }
    write32 (m_nBaseAddress + ARM_BSC_S__OFFSET, S_DONE);
    PeripheralExit ();
    m_SpinLock.Release ();
    return nResult;
}

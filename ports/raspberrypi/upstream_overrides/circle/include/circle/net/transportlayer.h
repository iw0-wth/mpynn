//
// transportlayer.h
//
// Circle - A C++ bare metal environment for Raspberry Pi
// Copyright (C) 2015-2026  R. Stange <rsta2@gmx.net>
// 
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with this program.  If not, see <http://www.gnu.org/licenses/>.
//
#ifndef _circle_net_transportlayer_h
#define _circle_net_transportlayer_h

#include <circle/net/netconfig.h>
#include <circle/net/networklayer.h>
#include <circle/net/netconnection.h>
#include <circle/net/tcprejector.h>
#include <circle/net/ipaddress.h>
#include <circle/net/netbuffer.h>
#include <circle/device.h>
#include <circle/ptrarray.h>
#include <circle/spinlock.h>
#include <circle/types.h>

class CTransportLayer
{
public:
	CTransportLayer (CNetConfig *pNetConfig, CNetworkLayer *pNetworkLayer);
	~CTransportLayer (void);

	boolean Initialize (void);

	void Process (void);

	// nOwnPort may be 0 (ephemeral port assignment, UDP only)
	int Bind (u16 nOwnPort, int nProtocol);

	// nOwnPort may be 0 (dynamic port assignment)
	int Connect (const CIPAddress &rIPAddress, u16 nPort, u16 nOwnPort, int nProtocol);

	int Listen (u16 nOwnPort, int nProtocol);
	boolean IsPortInUse (u16 nPort, int nProtocol);
	int Accept (CIPAddress *pForeignIP, u16 *pForeignPort, int hConnection);

	int Disconnect (int hConnection);
	int Shutdown (unsigned nHow, int hConnection);
	int SetUDPLocalAddress (const CIPAddress &rLocalIP, int hConnection);
	int SetUDPPeer (const CIPAddress &rForeignIP, u16 nForeignPort, int hConnection);
	// UDP only: 0 or a saved negative native error, cleared on take. Invalid
	// handle/protocol returns a negative native error using the same convention.
	int TakeUDPError (int hConnection);

	// TCP lifetime ownership only; neither call closes or deletes a connection.
	// Call on the cooperative scheduler core without yielding between Connect
	// and RetainConnection. A retained handle cannot be recycled until release.
	int RetainConnection (int hConnection);
	int ReleaseConnection (int hConnection);

	int Send (CNetBuffer *pData, int nFlags, int hConnection);

	int Receive (CNetBuffer **ppBuffer, int nFlags, int hConnection);

	int SendTo (CNetBuffer *pData, int nFlags,
		    const CIPAddress &rForeignIP, u16 nForeignPort, int hConnection);

	int ReceiveFrom (CNetBuffer **ppBuffer, int nFlags, CIPAddress *pForeignIP,
			 u16 *pForeignPort, int hConnection);

	int SetOptionReceiveTimeout (unsigned nMicroSeconds, int hConnection);
	int SetOptionSendTimeout (unsigned nMicroSeconds, int hConnection);
	// TCP only; validates the native slot before touching the connection.
	int SetOptionNoDelay (boolean bEnabled, int hConnection);

	int SetOptionBroadcast (boolean bAllowed, int hConnection);

	int SetOptionAddMembership (const CIPAddress &rGroupAddress, int hConnection);
	int SetOptionDropMembership (const CIPAddress &rGroupAddress, int hConnection);

	boolean IsConnected (int hConnection) const;
	const u8 *GetForeignIP (int hConnection) const;		// returns 0 if not connected
	u16 GetOwnPort (int hConnection) const;			// returns 0 if not assigned
	u16 GetMSS (int hConnection) const;

	CNetConnection::TStatus GetStatus (int hConnection) const;
	int GetTerminalError (int hConnection) const;
	boolean IsReceiveEOF (int hConnection) const;
	boolean IsAcceptReady (int hConnection) const;

	void ListConnections (CDevice *pTarget);

private:
	CNetConfig    *m_pNetConfig;
	CNetworkLayer *m_pNetworkLayer;

	CPtrArray m_pConnection;
	u16 m_nOwnPort;
	CSpinLock m_SpinLock;

	CTCPRejector m_TCPRejector;
};

#endif

//
// transportlayer.cpp
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
#include <circle/net/transportlayer.h>
#include <circle/net/tcpconnection.h>
#include <circle/net/udpconnection.h>
#include <circle/net/error.h>
#include <circle/net/in.h>
#include <circle/string.h>
#include <circle/macros.h>
#include <circle/util.h>
#include <assert.h>

#define OWN_PORT_MIN	60000
#define OWN_PORT_MAX	60999

CTransportLayer::CTransportLayer (CNetConfig *pNetConfig, CNetworkLayer *pNetworkLayer)
:	m_pNetConfig (pNetConfig),
	m_pNetworkLayer (pNetworkLayer),
	m_nOwnPort (OWN_PORT_MIN),
	m_SpinLock (TASK_LEVEL),
	m_TCPRejector (pNetConfig, pNetworkLayer)
{
	assert (m_pNetConfig != 0);
	assert (m_pNetworkLayer != 0);
}

CTransportLayer::~CTransportLayer (void)
{
	m_pNetworkLayer = 0;
	m_pNetConfig = 0;
}

boolean CTransportLayer::Initialize (void)
{
	return TRUE;
}

void CTransportLayer::Process (void)
{
	CNetBuffer *pNetBuffer;
	CIPAddress Sender;
	CIPAddress Receiver;
	int nProtocol;
	assert (m_pNetworkLayer != 0);
	while ((pNetBuffer = m_pNetworkLayer->Receive (&Sender, &Receiver, &nProtocol)) != 0)
	{
		unsigned i;
		for (i = 0; i < m_pConnection.GetCount (); i++)
		{
			if (m_pConnection[i] == 0)
			{
				continue;
			}

			if (((CNetConnection *) m_pConnection[i])->PacketReceived (
				pNetBuffer, Sender, Receiver, nProtocol) != 0)
			{
				pNetBuffer = 0;
				break;
			}
		}

		if (i >= m_pConnection.GetCount ())
		{
			// send RESET on not consumed TCP segment
			if (m_TCPRejector.PacketReceived (pNetBuffer,
							  Sender, Receiver, nProtocol) != 0)
			{
				pNetBuffer = 0;
			}
		}

		delete pNetBuffer;
	}

	TICMPNotificationType Type;
	u16 nSendPort;
	u16 nReceivePort;
	while (m_pNetworkLayer->ReceiveNotification (&Type, &Sender, &Receiver,
						     &nSendPort, &nReceivePort, &nProtocol))
	{
		unsigned i;
		for (i = 0; i < m_pConnection.GetCount (); i++)
		{
			if (m_pConnection[i] == 0)
			{
				continue;
			}

			if (((CNetConnection *) m_pConnection[i])->NotificationReceived (
				Type, Sender, Receiver, nSendPort, nReceivePort, nProtocol) != 0)
			{
				break;
			}
		}
	}

	for (unsigned i = 0; i < m_pConnection.GetCount (); i++)
	{
		if (m_pConnection[i] != 0)
		{
			if (!((CNetConnection *) m_pConnection[i])->IsTerminated ())
			{			
				((CNetConnection *) m_pConnection[i])->Process ();
			}
			else if (!((CNetConnection *) m_pConnection[i])->HasOwners ())
			{
				// Terminated owned connections retain terminal state and buffers,
				// but must not run Process again while awaiting owner release.
				delete (CNetConnection *) m_pConnection[i];
				m_pConnection[i] = 0;
			}
		}
	}

	m_SpinLock.Acquire ();

	// shrink m_pConnection
	unsigned nCount = m_pConnection.GetCount ();
	while (   nCount-- > 0
	       && m_pConnection[nCount] == 0)
	{
		m_pConnection.RemoveLast ();
	}

	m_SpinLock.Release ();
}

int CTransportLayer::Bind (u16 nOwnPort, int nProtocol)
{
	if (nProtocol != IPPROTO_UDP)
	{
		return -NET_ERROR_PROTOCOL_NOT_SUPPORTED;
	}

	m_SpinLock.Acquire ();

	unsigned i;
	for (i = 0; i < m_pConnection.GetCount (); i++)
	{
		if (m_pConnection[i] == 0)
		{
			break;
		}
	}

	if (i >= m_pConnection.GetCount ())
	{
		i = m_pConnection.Append (0);
	}

	if (nOwnPort == 0)		// assign ephemeral port
	{
		for (unsigned attempt = 0; attempt <= OWN_PORT_MAX - OWN_PORT_MIN; ++attempt)
		{
			u16 candidate = m_nOwnPort;
			if (++m_nOwnPort > OWN_PORT_MAX) m_nOwnPort = OWN_PORT_MIN;
			boolean occupied = FALSE;
			for (unsigned j = 0; j < m_pConnection.GetCount (); ++j)
			{
				CNetConnection *pConnection = (CNetConnection *) m_pConnection[j];
				if (pConnection && pConnection->GetOwnPort () == candidate
				    && pConnection->GetProtocol () == nProtocol) { occupied = TRUE; break; }
			}
			if (!occupied) { nOwnPort = candidate; break; }
		}
		if (nOwnPort == 0) { m_SpinLock.Release (); return -NET_ERROR_INVALID_VALUE; }
		// Keep the one acquired lock through construction; the common exit
		// below releases it exactly once (upstream released it twice here).
	}

	assert (m_pNetConfig != 0);
	assert (m_pNetworkLayer != 0);
	m_pConnection[i] = new CUDPConnection (m_pNetConfig, m_pNetworkLayer, nOwnPort);
	assert (m_pConnection[i] != 0);

	m_SpinLock.Release ();

	return i;
}

int CTransportLayer::Connect (const CIPAddress &rIPAddress, u16 nPort, u16 nOwnPort, int nProtocol)
{
	m_SpinLock.Acquire ();

	unsigned i;
	for (i = 0; i < m_pConnection.GetCount (); i++)
	{
		if (m_pConnection[i] == 0)
		{
			break;
		}
	}

	if (i >= m_pConnection.GetCount ())
	{
		i = m_pConnection.Append (0);
	}

	if (nOwnPort == 0)
	{
		for (unsigned attempt = 0; attempt <= OWN_PORT_MAX - OWN_PORT_MIN; ++attempt)
		{
			u16 candidate = m_nOwnPort;
			if (++m_nOwnPort > OWN_PORT_MAX) m_nOwnPort = OWN_PORT_MIN;
			boolean occupied = FALSE;
			for (unsigned j = 0; j < m_pConnection.GetCount (); ++j)
			{
				CNetConnection *pConnection = (CNetConnection *) m_pConnection[j];
				if (pConnection && pConnection->GetOwnPort () == candidate
				    && pConnection->GetProtocol () == nProtocol) { occupied = TRUE; break; }
			}
			if (!occupied) { nOwnPort = candidate; break; }
		}
		if (nOwnPort == 0) { m_SpinLock.Release (); return -NET_ERROR_INVALID_VALUE; }
	}

	assert (m_pNetConfig != 0);
	assert (m_pNetworkLayer != 0);
	switch (nProtocol)
	{
	case IPPROTO_TCP:
		m_pConnection[i] = new CTCPConnection (m_pNetConfig, m_pNetworkLayer, rIPAddress, nPort, nOwnPort);
		break;

	case IPPROTO_UDP:
		m_pConnection[i] = new CUDPConnection (m_pNetConfig, m_pNetworkLayer, rIPAddress, nPort, nOwnPort);
		break;

	default:
		m_SpinLock.Release ();
		return -NET_ERROR_PROTOCOL_NOT_SUPPORTED;
	}

	m_SpinLock.Release ();

	assert (m_pConnection[i] != 0);
	int nResult = ((CNetConnection *) m_pConnection[i])->Connect ();
	if (nResult < 0)
	{
		return nResult;
	}
	
	return i;
}

boolean CTransportLayer::IsPortInUse (u16 nPort, int nProtocol)
{
	if (nPort == 0) return FALSE;
	m_SpinLock.Acquire ();
	for (unsigned i = 0; i < m_pConnection.GetCount (); ++i)
	{
		CNetConnection *pConnection = (CNetConnection *)m_pConnection[i];
		if (pConnection && pConnection->GetOwnPort () == nPort
		    && pConnection->GetProtocol () == nProtocol)
		{
			m_SpinLock.Release ();
			return TRUE;
		}
	}
	m_SpinLock.Release ();
	return FALSE;
}

int CTransportLayer::Listen (u16 nOwnPort, int nProtocol)
{
	m_SpinLock.Acquire ();

	unsigned i;
	for (i = 0; i < m_pConnection.GetCount (); i++)
	{
		if (m_pConnection[i] == 0)
		{
			break;
		}
	}

	if (i >= m_pConnection.GetCount ())
	{
		i = m_pConnection.Append (0);
	}

	if (nOwnPort == 0)
	{
		// Bounded ephemeral search includes connected and retained closed TCP
		// handles. UDP uses an independent protocol namespace.
		for (unsigned attempt = 0; attempt <= OWN_PORT_MAX - OWN_PORT_MIN; ++attempt)
		{
			u16 candidate = m_nOwnPort;
			if (++m_nOwnPort > OWN_PORT_MAX) m_nOwnPort = OWN_PORT_MIN;
			boolean occupied = FALSE;
			for (unsigned j = 0; j < m_pConnection.GetCount (); ++j)
			{
				CNetConnection *pConnection = (CNetConnection *) m_pConnection[j];
				if (pConnection && pConnection->GetOwnPort () == candidate
				    && pConnection->GetProtocol () == IPPROTO_TCP) { occupied = TRUE; break; }
			}
			if (!occupied) { nOwnPort = candidate; break; }
		}
		if (nOwnPort == 0) { m_SpinLock.Release (); return -NET_ERROR_INVALID_VALUE; }
	}

	if (nProtocol != IPPROTO_TCP)
	{
		m_SpinLock.Release ();

		return -NET_ERROR_PROTOCOL_NOT_SUPPORTED;
	}

	assert (m_pNetConfig != 0);
	assert (m_pNetworkLayer != 0);
	m_pConnection[i] = new CTCPConnection (m_pNetConfig, m_pNetworkLayer, nOwnPort);
	assert (m_pConnection[i] != 0);

	m_SpinLock.Release ();

	return i;
}

int CTransportLayer::Accept (CIPAddress *pForeignIP, u16 *pForeignPort, int hConnection)
{
	assert (hConnection >= 0);
	if (   hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_INVALID_VALUE;
	}

	assert (pForeignIP != 0);
	assert (pForeignPort != 0);
	return ((CNetConnection *) m_pConnection[hConnection])->Accept (pForeignIP, pForeignPort);
}

int CTransportLayer::SetUDPLocalAddress (const CIPAddress &rLocalIP, int hConnection)
{
	if (hConnection < 0 || hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_INVALID_VALUE;
	}

	CNetConnection *pConnection = (CNetConnection *) m_pConnection[hConnection];
	if (pConnection->GetProtocol () != IPPROTO_UDP)
	{
		return -NET_ERROR_PROTOCOL_NOT_SUPPORTED;
	}

	return ((CUDPConnection *) pConnection)->SetLocalAddress (rLocalIP);
}

int CTransportLayer::SetUDPPeer (const CIPAddress &rForeignIP, u16 nForeignPort, int hConnection)
{
	if (hConnection < 0 || hConnection >= (int)m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0) return -NET_ERROR_INVALID_VALUE;
	CNetConnection *pConnection = (CNetConnection *) m_pConnection[hConnection];
	if (pConnection->GetProtocol () != IPPROTO_UDP) return -NET_ERROR_PROTOCOL_NOT_SUPPORTED;
	return ((CUDPConnection *)pConnection)->SetPeer (rForeignIP, nForeignPort);
}

int CTransportLayer::TakeUDPError (int hConnection)
{
	if (hConnection < 0 || hConnection >= (int)m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0) return -NET_ERROR_INVALID_VALUE;
	CNetConnection *pConnection = (CNetConnection *) m_pConnection[hConnection];
	if (pConnection->GetProtocol () != IPPROTO_UDP) return -NET_ERROR_PROTOCOL_NOT_SUPPORTED;
	return ((CUDPConnection *)pConnection)->TakePendingError ();
}

int CTransportLayer::Disconnect (int hConnection)
{
	assert (hConnection >= 0);
	if (   hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_INVALID_VALUE;
	}

	return ((CNetConnection *) m_pConnection[hConnection])->Close ();
}

int CTransportLayer::Shutdown (unsigned nHow, int hConnection)
{
	if (nHow > 2)
	{
		return -NET_ERROR_INVALID_VALUE;
	}
	if (hConnection < 0 || hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_NOT_CONNECTED;
	}
	CNetConnection *pConnection = (CNetConnection *) m_pConnection[hConnection];
	if (pConnection->GetProtocol () != IPPROTO_TCP)
	{
		return -NET_ERROR_PROTOCOL_NOT_SUPPORTED;
	}
	return ((CTCPConnection *) pConnection)->Shutdown (nHow);
}

int CTransportLayer::RetainConnection (int hConnection)
{
	if (   hConnection < 0
	    || hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_INVALID_VALUE;
	}

	CNetConnection *pConnection = (CNetConnection *) m_pConnection[hConnection];
	if (pConnection->GetProtocol () != IPPROTO_TCP)
	{
		return -NET_ERROR_PROTOCOL_NOT_SUPPORTED;
	}

	pConnection->RetainOwner ();
	return 0;
}

int CTransportLayer::ReleaseConnection (int hConnection)
{
	if (   hConnection < 0
	    || hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_INVALID_VALUE;
	}

	CNetConnection *pConnection = (CNetConnection *) m_pConnection[hConnection];
	if (pConnection->GetProtocol () != IPPROTO_TCP)
	{
		return -NET_ERROR_PROTOCOL_NOT_SUPPORTED;
	}
	if (!pConnection->HasOwners ())
	{
		return -NET_ERROR_INVALID_VALUE;
	}

	pConnection->ReleaseOwner ();
	return 0;
}

int CTransportLayer::Send (CNetBuffer *pNetBuffer, int nFlags, int hConnection)
{
	assert (hConnection >= 0);
	if (   hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_NOT_CONNECTED;
	}

	assert (pNetBuffer != 0);
	return ((CNetConnection *) m_pConnection[hConnection])->Send (pNetBuffer, nFlags);
}

int CTransportLayer::Receive (CNetBuffer **ppNetBuffer, int nFlags, int hConnection)
{
	assert (hConnection >= 0);
	if (   hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_NOT_CONNECTED;
	}

	assert (ppNetBuffer != 0);
	return ((CNetConnection *) m_pConnection[hConnection])->Receive (ppNetBuffer, nFlags);
}

int CTransportLayer::SendTo (CNetBuffer *pNetBuffer, int nFlags,
			     const CIPAddress &rForeignIP, u16 nForeignPort, int hConnection)
{
	assert (hConnection >= 0);
	if (   hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_NOT_CONNECTED;
	}

	assert (pNetBuffer != 0);
	return ((CNetConnection *) m_pConnection[hConnection])->SendTo (pNetBuffer, nFlags,
									rForeignIP, nForeignPort);
}

int CTransportLayer::ReceiveFrom (CNetBuffer **ppNetBuffer, int nFlags, CIPAddress *pForeignIP,
				  u16 *pForeignPort, int hConnection)
{
	assert (hConnection >= 0);
	if (   hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_NOT_CONNECTED;
	}

	assert (ppNetBuffer != 0);
	return ((CNetConnection *) m_pConnection[hConnection])->ReceiveFrom (ppNetBuffer, nFlags,
									     pForeignIP,
									     pForeignPort);
}

int CTransportLayer::SetOptionReceiveTimeout (unsigned nMicroSeconds, int hConnection)
{
	assert (hConnection >= 0);
	if (   hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_NOT_CONNECTED;
	}

	return ((CNetConnection *) m_pConnection[hConnection])->SetOptionReceiveTimeout (nMicroSeconds);
}

int CTransportLayer::SetOptionSendTimeout (unsigned nMicroSeconds, int hConnection)
{
	assert (hConnection >= 0);
	if (   hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_NOT_CONNECTED;
	}

	return ((CNetConnection *) m_pConnection[hConnection])->SetOptionSendTimeout (nMicroSeconds);
}

int CTransportLayer::SetOptionNoDelay (boolean bEnabled, int hConnection)
{
	if (   hConnection < 0
	    || hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_INVALID_VALUE;
	}

	CNetConnection *pConnection = (CNetConnection *) m_pConnection[hConnection];
	if (pConnection->GetProtocol () != IPPROTO_TCP)
	{
		return -NET_ERROR_PROTOCOL_NOT_SUPPORTED;
	}

	return ((CTCPConnection *) pConnection)->SetOptionNoDelay (bEnabled);
}

int CTransportLayer::SetOptionBroadcast (boolean bAllowed, int hConnection)
{
	assert (hConnection >= 0);
	if (   hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_INVALID_VALUE;
	}

	return ((CNetConnection *) m_pConnection[hConnection])->SetOptionBroadcast (bAllowed);
}

int CTransportLayer::SetOptionAddMembership (const CIPAddress &rGroupAddress, int hConnection)
{
	assert (hConnection >= 0);
	if (   hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_INVALID_VALUE;
	}

	return ((CNetConnection *) m_pConnection[hConnection])->SetOptionAddMembership (rGroupAddress);
}

int CTransportLayer::SetOptionDropMembership (const CIPAddress &rGroupAddress, int hConnection)
{
	assert (hConnection >= 0);
	if (   hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_INVALID_VALUE;
	}

	return ((CNetConnection *) m_pConnection[hConnection])->SetOptionDropMembership (rGroupAddress);
}

boolean CTransportLayer::IsConnected (int hConnection) const
{
	assert (hConnection >= 0);
	if (   hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return 0;
	}

	return ((CNetConnection *) m_pConnection[hConnection])->IsConnected ();
}

const u8 *CTransportLayer::GetForeignIP (int hConnection) const
{
	assert (hConnection >= 0);
	if (   hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return 0;
	}

	return ((CNetConnection *) m_pConnection[hConnection])->GetForeignIP ();
}

u16 CTransportLayer::GetOwnPort (int hConnection) const
{
	assert (hConnection >= 0);
	if (   hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return 0;
	}

	return ((CNetConnection *) m_pConnection[hConnection])->GetOwnPort ();
}

u16 CTransportLayer::GetMSS (int hConnection) const
{
	assert (hConnection >= 0);
	if (   hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return 0;
	}

	return ((CNetConnection *) m_pConnection[hConnection])->GetMSS ();
}

int CTransportLayer::GetTerminalError (int hConnection) const
{
	assert (hConnection >= 0);
	if (hConnection < 0 || hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return -NET_ERROR_INVALID_VALUE;
	}
	return ((CNetConnection *) m_pConnection[hConnection])->GetTerminalError ();
}

boolean CTransportLayer::IsReceiveEOF (int hConnection) const
{
	if (hConnection < 0 || hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0) return FALSE;
	return ((CNetConnection *) m_pConnection[hConnection])->IsReceiveEOF ();
}

boolean CTransportLayer::IsAcceptReady (int hConnection) const
{
	if (hConnection < 0 || hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0) return FALSE;
	return ((CNetConnection *) m_pConnection[hConnection])->IsAcceptReady ();
}

CNetConnection::TStatus CTransportLayer::GetStatus (int hConnection) const
{
	assert (hConnection >= 0);
	if (   hConnection >= (int) m_pConnection.GetCount ()
	    || m_pConnection[hConnection] == 0)
	{
		return {FALSE, FALSE, FALSE, FALSE};
	}

	return ((CNetConnection *) m_pConnection[hConnection])->GetStatus ();
}

void CTransportLayer::ListConnections (CDevice *pTarget)
{
	assert (pTarget != 0);

	static const char Header[] = "PROT LOCAL ADDRESS         FOREIGN ADDRESS       STATE\n";
	pTarget->Write (Header, sizeof Header-1);

	CString OwnIP, Local, Foreign, Line;

	assert (m_pNetConfig != 0);
	const CIPAddress *pOwnIP = m_pNetConfig->GetIPAddress ();
	assert (pOwnIP != 0);
	pOwnIP->Format (&OwnIP);

	for (unsigned i = 0; i < m_pConnection.GetCount (); i++)
	{
		if (   m_pConnection[i] == 0
		    || ((CNetConnection *) m_pConnection[i])->IsTerminated ())
		{
			continue;
		}

		int nProtocol = ((CNetConnection *) m_pConnection[i])->GetProtocol ();
		assert (nProtocol == IPPROTO_TCP || nProtocol == IPPROTO_UDP);
		const char *pProtocol = nProtocol == IPPROTO_TCP ? "tcp" : "udp";

		Local.Format ("%s:%u", (const char *) OwnIP,
			      (unsigned) ((CNetConnection *) m_pConnection[i])->GetOwnPort ());

		const u8 *pForeignIP =
			((CNetConnection *) m_pConnection[i])->GetForeignIP ();
		Foreign.Format ("%u.%u.%u.%u:%u",
			(unsigned) pForeignIP[0], (unsigned) pForeignIP[1],
			(unsigned) pForeignIP[2], (unsigned) pForeignIP[3],
			(unsigned) ((CNetConnection *) m_pConnection[i])->GetForeignPort ());

		Line.Format ("%-4s %-21s %-21s %s\n", pProtocol,
			     (const char *) Local, (const char *) Foreign,
			     ((CNetConnection *) m_pConnection[i])->GetStateName ());

		pTarget->Write ((const char *) Line, Line.GetLength ());
	}
}

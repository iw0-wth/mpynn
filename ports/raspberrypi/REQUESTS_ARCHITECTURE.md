# Requests and TLS architecture

The Raspberry Pi port freezes `requests` from the read-only micropython-lib through
`manifest.py`. There is no Raspberry-Pi-specific Python requests implementation.
Python code therefore uses the same requests/tls API as other MicroPython ports.

TLS implementation remains MicroPython's standard mbedTLS extension. Raspberry Pi
specific random source, clock and socket behavior are provided below the Python API
by port C/C++ glue. The standard micropython-lib requests package uses `tls.SSLContext`
with the default CERT_NONE policy and `server_hostname`; callers needing certificate
verification should use the standard tls/socket API directly. The port no longer
adds an `ssl_context=` requests keyword.

The frozen package is verified by the normal ARM build; physical HTTPS and certificate
chain behavior still require board testing.

"""Server-configured ClamAV INSTREAM scanner; failures never mean clean."""
import socket
import struct

from django.conf import settings


class ClamAVScanner:
    def scan(self, content: bytes) -> str:
        host = getattr(settings, "DAWATRACE_MALWARE_SCANNER_HOST", "")
        if not host:
            return "NOT_CONFIGURED"
        try:
            with socket.create_connection(
                (host, getattr(settings, "DAWATRACE_MALWARE_SCANNER_PORT", 3310)), timeout=10
            ) as connection:
                connection.sendall(b"zINSTREAM\x00")
                for offset in range(0, len(content), 65536):
                    chunk = content[offset:offset + 65536]
                    connection.sendall(struct.pack("!I", len(chunk)) + chunk)
                connection.sendall(struct.pack("!I", 0))
                result = b""
                while b"\x00" not in result and len(result) < 4096:
                    chunk = connection.recv(1024)
                    if not chunk:
                        break
                    result += chunk
            if result.rstrip(b"\x00\r\n") == b"stream: OK":
                return "CLEAN"
            return "INFECTED" if b" FOUND" in result else "ERROR"
        except (OSError, ValueError):
            return "ERROR"

import struct

import pytest

from apps.documents.scanning import ClamAVScanner


@pytest.mark.parametrize("reply,expected", [(b"stream: OK\x00", "CLEAN"), (b"stream: Eicar FOUND\x00", "INFECTED"), (b"stream: size ERROR\x00", "ERROR"), (b"", "ERROR")])
def test_clamav_stream_protocol_requires_explicit_clean_result(settings, monkeypatch, reply, expected):
    settings.DAWATRACE_MALWARE_SCANNER_HOST = "private-scanner"
    settings.DAWATRACE_MALWARE_SCANNER_PORT = 3310
    sent = []
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def sendall(self, data):
            sent.append(data)
        def recv(self, size):
            return reply
    def connect(address, timeout):
        assert address == ("private-scanner", 3310) and timeout == 10
        return Connection()
    monkeypatch.setattr("apps.documents.scanning.socket.create_connection", connect)
    assert ClamAVScanner().scan(b"source bytes") == expected
    assert b"".join(sent) == b"zINSTREAM\x00" + struct.pack("!I", len(b"source bytes")) + b"source bytes" + struct.pack("!I", 0)


def test_clamav_missing_configuration_and_network_error_never_mean_clean(settings, monkeypatch):
    settings.DAWATRACE_MALWARE_SCANNER_HOST = ""
    assert ClamAVScanner().scan(b"source bytes") == "NOT_CONFIGURED"
    settings.DAWATRACE_MALWARE_SCANNER_HOST = "private-scanner"
    def connect(*args, **kwargs):
        raise TimeoutError("unavailable")
    monkeypatch.setattr("apps.documents.scanning.socket.create_connection", connect)
    assert ClamAVScanner().scan(b"source bytes") == "ERROR"

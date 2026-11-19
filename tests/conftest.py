import socket

import pytest

from preheat.fixture import day

LOOPBACK = ("127.0.0.1", "::1", "localhost")


@pytest.fixture(params=["current", "insulated"])
def nominal(request):
    return request.param, day("nominal", request.param)


@pytest.fixture(autouse=True)
def block_network(request, monkeypatch):
    """No outbound sockets in tests. Tests marked `loopback` may reach 127.0.0.1 only."""
    allowed = request.node.get_closest_marker("loopback") is not None
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def permitted(address):
        return allowed and isinstance(address, tuple) and address[0] in LOOPBACK

    def connect(self, address):
        if not permitted(address):
            raise OSError(f"network access is blocked in tests: {address!r}")
        return real_connect(self, address)

    def connect_ex(self, address):
        if not permitted(address):
            raise OSError(f"network access is blocked in tests: {address!r}")
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if not (allowed and host in LOOPBACK):
            raise OSError(f"name lookup is blocked in tests: {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)

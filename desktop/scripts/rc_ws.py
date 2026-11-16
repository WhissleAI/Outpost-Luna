"""A minimal WebSocket client (RFC 6455) on the standard library, for the release gates (release_check.py).

Stdlib only on purpose: the gates run under any Python 3.9+, including the installed app's own embedded Python on
Windows, and the protocol fuzzer needs to send frames a well-behaved library refuses to build (bad opcodes, unmasked
frames, lying length fields, invalid UTF-8, fragments that never finish).

    ws = WS.connect("ws://127.0.0.1:47310/ws/listen", headers={"X-Luna-Token": tok})
    ws.send_binary(pcm); ws.send_text('{"t":"stop"}'); msg = ws.recv(timeout=5)   # -> str | bytes | None (closed)
    ws.send_frame(opcode, payload, fin=True, mask=True, rsv=0, length=None)        # anything, for the fuzzer
"""
from __future__ import annotations

import base64
import os
import socket
import struct
import time
from urllib.parse import urlsplit

OP_CONT, OP_TEXT, OP_BIN, OP_CLOSE, OP_PING, OP_PONG = 0, 1, 2, 8, 9, 10


class Closed(Exception):
    """The server closed the connection (code in .code, None when the TCP stream just ended)."""

    def __init__(self, code=None, reason=""):
        super().__init__(f"closed {code} {reason}".strip())
        self.code, self.reason = code, reason


class HandshakeError(Exception):
    def __init__(self, status: int, head: str):
        super().__init__(f"handshake refused: HTTP {status}")
        self.status, self.head = status, head


class WS:
    def __init__(self, sock: socket.socket, leftover: bytes = b""):
        self.sock, self.buf = sock, leftover
        self.closed = None

    # ---- connect ----
    @classmethod
    def connect(cls, url: str, headers: dict | None = None, timeout: float = 10.0, raw_request: bytes | None = None):
        u = urlsplit(url)
        host, port = u.hostname, u.port or 80
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        s = socket.create_connection((host, port), timeout=timeout)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if raw_request is None:
            key = base64.b64encode(os.urandom(16)).decode()
            lines = [f"GET {path} HTTP/1.1", f"Host: {host}:{port}", "Upgrade: websocket", "Connection: Upgrade",
                     f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
            lines += [f"{k}: {v}" for k, v in (headers or {}).items()]
            raw_request = ("\r\n".join(lines) + "\r\n\r\n").encode()
        s.sendall(raw_request)
        data = b""
        deadline = time.monotonic() + timeout
        while b"\r\n\r\n" not in data:
            if time.monotonic() > deadline:
                s.close()
                raise HandshakeError(0, "timeout")
            chunk = s.recv(4096)
            if not chunk:
                s.close()
                raise HandshakeError(0, data.decode("latin-1")[:200])
            data += chunk
        head, rest = data.split(b"\r\n\r\n", 1)
        status_line = head.split(b"\r\n", 1)[0].decode("latin-1")
        try:
            status = int(status_line.split()[1])
        except (IndexError, ValueError):
            status = 0
        if status != 101:
            s.close()
            raise HandshakeError(status, head.decode("latin-1")[:300])
        return cls(s, rest)

    # ---- send ----
    def send_frame(self, opcode: int, payload: bytes = b"", fin: bool = True, mask: bool = True, rsv: int = 0,
                   length: int | None = None) -> None:
        """Any frame. length overrides the length field (a lie, for the fuzzer); mask=False sends it unmasked."""
        n = len(payload) if length is None else length
        b0 = (0x80 if fin else 0) | ((rsv & 7) << 4) | (opcode & 0xF)
        if n < 126:
            hdr = struct.pack("!BB", b0, (0x80 if mask else 0) | n)
        elif n < 65536:
            hdr = struct.pack("!BBH", b0, (0x80 if mask else 0) | 126, n)
        else:
            hdr = struct.pack("!BBQ", b0, (0x80 if mask else 0) | 127, n & 0xFFFFFFFFFFFFFFFF)
        if mask:
            mk = os.urandom(4)
            payload = _xor(payload, mk)
            hdr += mk
        self.sock.sendall(hdr + payload)

    def send_text(self, s: str) -> None:
        self.send_frame(OP_TEXT, s.encode("utf-8"))

    def send_binary(self, b: bytes) -> None:
        self.send_frame(OP_BIN, b)

    def close(self, code: int = 1000) -> None:
        try:
            self.send_frame(OP_CLOSE, struct.pack("!H", code))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    # ---- receive ----
    def _read(self, n: int, deadline: float) -> bytes:
        while len(self.buf) < n:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError
            self.sock.settimeout(left)
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                raise TimeoutError from None
            if not chunk:
                raise Closed(None, "eof")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self, timeout: float = 10.0):
        """The next whole message: str (text) or bytes (binary). Raises TimeoutError, Closed."""
        deadline = time.monotonic() + timeout
        parts, op0 = [], None
        while True:
            b0, b1 = self._read(2, deadline)
            op, fin, n = b0 & 0xF, b0 & 0x80, b1 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read(2, deadline))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read(8, deadline))[0]
            mk = self._read(4, deadline) if b1 & 0x80 else None
            data = self._read(n, deadline) if n else b""
            if mk:
                data = _xor(data, mk)
            if op == OP_CLOSE:
                code = struct.unpack("!H", data[:2])[0] if len(data) >= 2 else None
                self.closed = code
                try:
                    self.sock.close()
                except OSError:
                    pass
                raise Closed(code, data[2:].decode("utf-8", "replace"))
            if op == OP_PING:
                self.send_frame(OP_PONG, data)
                continue
            if op == OP_PONG:
                continue
            if op in (OP_TEXT, OP_BIN):
                op0, parts = op, [data]
            else:
                parts.append(data)
            if fin:
                msg = b"".join(parts)
                return msg.decode("utf-8", "replace") if op0 == OP_TEXT else msg


def _xor(data: bytes, mk: bytes) -> bytes:
    if not data:
        return data
    n = len(data)
    k = (mk * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "little") ^ int.from_bytes(k, "little")).to_bytes(n, "little")

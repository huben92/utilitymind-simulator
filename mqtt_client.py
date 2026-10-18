"""Small MQTT 3.1.1 QoS 1 publisher using the Python standard library."""

import socket
import ssl
import struct


def _remaining_length(value):
    data = bytearray()
    while True:
        digit = value % 128
        value //= 128
        if value:
            digit |= 128
        data.append(digit)
        if not value:
            return bytes(data)


def _utf8(value):
    raw = value.encode("utf-8")
    return struct.pack("!H", len(raw)) + raw


def _read_exact(sock, length):
    output = bytearray()
    while len(output) < length:
        part = sock.recv(length - len(output))
        if not part:
            raise ConnectionError("Broker closed the connection")
        output.extend(part)
    return bytes(output)


def _read_packet(sock):
    header = _read_exact(sock, 1)[0]
    multiplier, remaining = 1, 0
    for _ in range(4):
        digit = _read_exact(sock, 1)[0]
        remaining += (digit & 127) * multiplier
        if not digit & 128:
            return header, _read_exact(sock, remaining)
        multiplier *= 128
    raise ValueError("Invalid MQTT packet length")


class MQTTClient:
    def __init__(self, host, port, client_id, username="", password="", use_tls=False, ca_cert=None):
        self.host, self.port, self.client_id = host, int(port), client_id
        self.username, self.password, self.use_tls = username, password, use_tls
        self.ca_cert = ca_cert
        self.sock = None
        self.packet_id = 0

    def connect(self):
        raw = socket.create_connection((self.host, self.port), timeout=8)
        raw.settimeout(8)
        try:
            self.sock = ssl.create_default_context(cafile=self.ca_cert).wrap_socket(raw, server_hostname=self.host) if self.use_tls else raw
            flags = 0x02  # Clean session.
            if self.username:
                flags |= 0x80
            if self.password:
                flags |= 0x40
            payload = _utf8(self.client_id)
            if self.username:
                payload += _utf8(self.username)
            if self.password:
                payload += _utf8(self.password)
            variable = _utf8("MQTT") + bytes([4, flags]) + struct.pack("!H", 30)
            body = variable + payload
            self.sock.sendall(bytes([0x10]) + _remaining_length(len(body)) + body)
            header, response = _read_packet(self.sock)
            if header != 0x20 or len(response) != 2 or response[1] != 0:
                code = response[1] if len(response) > 1 else "invalid response"
                raise ConnectionError(f"MQTT connection rejected: {code}")
        except Exception:
            self.close()
            raise

    def publish(self, topic, payload):
        self.packet_id = self.packet_id % 65535 + 1
        body = _utf8(topic) + struct.pack("!H", self.packet_id) + payload.encode("utf-8")
        self.sock.sendall(bytes([0x32]) + _remaining_length(len(body)) + body)
        header, response = _read_packet(self.sock)
        if header != 0x40 or response != struct.pack("!H", self.packet_id):
            raise ConnectionError("Missing MQTT PUBACK")

    def close(self):
        if self.sock:
            try:
                self.sock.sendall(b"\xe0\x00")
                self.sock.close()
            except OSError:
                pass
            self.sock = None

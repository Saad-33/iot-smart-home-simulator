"""
Pure-Python AsyncIO MQTT 3.1.1 Broker.
Supports CONNECT, PUBLISH, SUBSCRIBE, UNSUBSCRIBE, PINGREQ, DISCONNECT.
Features:
 - Retained messages with optional disk persistence
 - Last Will and Testament (LWT)
 - Topic wildcard matching (+ and #)
 - QoS 0 and QoS 1 (PUBACK/SUBACK)
 - Clean disconnect vs abrupt disconnection handling
"""

import asyncio
import json
import logging
import os
import struct
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("MQTTBroker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [Broker] %(message)s")


def encode_remaining_length(length: int) -> bytes:
    encoded = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length > 0:
            digit |= 0x80
        encoded.append(digit)
        if length == 0:
            break
    return bytes(encoded)


async def decode_remaining_length(reader: asyncio.StreamReader) -> int:
    multiplier = 1
    value = 0
    while True:
        raw = await reader.readexactly(1)
        byte = raw[0]
        value += (byte & 127) * multiplier
        multiplier *= 128
        if (byte & 128) == 0:
            break
        if multiplier > 128 * 128 * 128:
            raise ValueError("Malformed remaining length")
    return value


def topic_matches(pattern: str, topic: str) -> bool:
    """MQTT topic matching with + (single level) and # (multi level) wildcards."""
    if pattern == topic or pattern == "#":
        return True
    p_parts = pattern.split("/")
    t_parts = topic.split("/")

    i = 0
    while i < len(p_parts):
        p = p_parts[i]
        if p == "#":
            return True
        if i >= len(t_parts):
            return False
        t = t_parts[i]
        if p != "+" and p != t:
            return False
        i += 1
    return i == len(t_parts)


class MQTTClientSession:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, broker: "MQTTBroker"):
        self.reader = reader
        self.writer = writer
        self.broker = broker
        self.client_id: str = ""
        self.clean_session: bool = True
        self.subscriptions: Dict[str, int] = {}  # topic_filter -> qos
        self.will_topic: Optional[str] = None
        self.will_message: Optional[bytes] = None
        self.will_qos: int = 0
        self.will_retain: bool = False
        self.connected = False
        self.clean_disconnect = False

    async def send_packet(self, data: bytes):
        try:
            self.writer.write(data)
            await self.writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass

    async def handle_connect(self, flags: int, data: bytes):
        name_len = struct.unpack("!H", data[0:2])[0]
        proto_name = data[2 : 2 + name_len].decode("utf-8", errors="ignore")
        idx = 2 + name_len
        proto_level = data[idx]
        idx += 1
        conn_flags = data[idx]
        idx += 1
        keep_alive = struct.unpack("!H", data[idx : idx + 2])[0]
        idx += 2

        self.clean_session = bool(conn_flags & 0x02)
        will_flag = bool(conn_flags & 0x04)
        self.will_qos = (conn_flags >> 3) & 0x03
        self.will_retain = bool(conn_flags & 0x20)

        # Client identifier
        cid_len = struct.unpack("!H", data[idx : idx + 2])[0]
        idx += 2
        self.client_id = data[idx : idx + cid_len].decode("utf-8", errors="ignore")
        idx += cid_len

        if will_flag:
            w_topic_len = struct.unpack("!H", data[idx : idx + 2])[0]
            idx += 2
            self.will_topic = data[idx : idx + w_topic_len].decode("utf-8", errors="ignore")
            idx += w_topic_len
            w_msg_len = struct.unpack("!H", data[idx : idx + 2])[0]
            idx += 2
            self.will_message = data[idx : idx + w_msg_len]
            idx += w_msg_len

        # Acknowledge connection (CONNACK: 0x20, 0x02, session_present=0, return_code=0)
        connack = bytes([0x20, 0x02, 0x00, 0x00])
        await self.send_packet(connack)
        self.connected = True
        logger.info(f"Client connected: {self.client_id} (clean_session={self.clean_session})")

    async def handle_subscribe(self, packet_id: int, payload: bytes):
        granted_qos = []
        idx = 0
        while idx < len(payload):
            t_len = struct.unpack("!H", payload[idx : idx + 2])[0]
            idx += 2
            topic = payload[idx : idx + t_len].decode("utf-8", errors="ignore")
            idx += t_len
            requested_qos = payload[idx]
            idx += 1
            qos = min(requested_qos, 1)  # grant up to QoS 1
            self.subscriptions[topic] = qos
            granted_qos.append(qos)
            logger.debug(f"Client {self.client_id} subscribed to '{topic}' QoS {qos}")

            # Send retained messages matching this subscription
            for r_topic, (r_payload, r_qos) in self.broker.retained_messages.items():
                if topic_matches(topic, r_topic):
                    await self.broker.send_publish(self, r_topic, r_payload, qos=r_qos, retain=True)

        # SUBACK packet: 0x90, length, packet_id (2 bytes), return codes
        suback_payload = struct.pack("!H", packet_id) + bytes(granted_qos)
        suback = bytes([0x90]) + encode_remaining_length(len(suback_payload)) + suback_payload
        await self.send_packet(suback)

    async def handle_unsubscribe(self, packet_id: int, payload: bytes):
        idx = 0
        while idx < len(payload):
            t_len = struct.unpack("!H", payload[idx : idx + 2])[0]
            idx += 2
            topic = payload[idx : idx + t_len].decode("utf-8", errors="ignore")
            idx += t_len
            self.subscriptions.pop(topic, None)
            logger.debug(f"Client {self.client_id} unsubscribed from '{topic}'")

        # UNSUBACK packet: 0xB0, 0x02, packet_id
        unsuback = bytes([0xB0, 0x02]) + struct.pack("!H", packet_id)
        await self.send_packet(unsuback)

    async def handle_publish(self, flags: int, data: bytes):
        qos = (flags >> 1) & 0x03
        retain = bool(flags & 0x01)
        idx = 0
        t_len = struct.unpack("!H", data[idx : idx + 2])[0]
        idx += 2
        topic = data[idx : idx + t_len].decode("utf-8", errors="ignore")
        idx += t_len

        packet_id = None
        if qos > 0:
            packet_id = struct.unpack("!H", data[idx : idx + 2])[0]
            idx += 2

        payload = data[idx:]

        # Handle QoS 1 PUBACK
        if qos == 1 and packet_id is not None:
            puback = bytes([0x40, 0x02]) + struct.pack("!H", packet_id)
            await self.send_packet(puback)

        # Retain handling
        if retain:
            if len(payload) > 0:
                self.broker.retained_messages[topic] = (payload, qos)
            else:
                self.broker.retained_messages.pop(topic, None)
            self.broker.save_retained_to_disk()

        # Forward to all matching subscribers
        await self.broker.broadcast(topic, payload, qos=qos)


class MQTTBroker:
    def __init__(self, host: str = "127.0.0.1", port: int = 1883, storage_path: str = "data/broker_retained.json"):
        self.host = host
        self.port = port
        self.storage_path = storage_path
        self.sessions: Set[MQTTClientSession] = set()
        self.retained_messages: Dict[str, Tuple[bytes, int]] = {}  # topic -> (payload_bytes, qos)
        self.server: Optional[asyncio.Server] = None
        self._packet_id_counter = 1
        self.load_retained_from_disk()

    def next_packet_id(self) -> int:
        self._packet_id_counter = (self._packet_id_counter % 65535) + 1
        return self._packet_id_counter

    def load_retained_from_disk(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for topic, item in data.items():
                        payload = bytes.fromhex(item["hex"])
                        qos = item.get("qos", 0)
                        self.retained_messages[topic] = (payload, qos)
                logger.info(f"Loaded {len(self.retained_messages)} retained messages from {self.storage_path}")
            except Exception as e:
                logger.warning(f"Failed to load retained messages: {e}")

    def save_retained_to_disk(self):
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            data = {}
            for topic, (payload, qos) in self.retained_messages.items():
                data[topic] = {"hex": payload.hex(), "qos": qos}
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save retained messages: {e}")

    async def send_publish(self, session: MQTTClientSession, topic: str, payload: bytes, qos: int = 0, retain: bool = False):
        flags = (qos << 1) | (1 if retain else 0)
        t_bytes = topic.encode("utf-8")
        var_header = struct.pack("!H", len(t_bytes)) + t_bytes
        if qos > 0:
            pid = self.next_packet_id()
            var_header += struct.pack("!H", pid)

        body = var_header + payload
        packet = bytes([0x30 | flags]) + encode_remaining_length(len(body)) + body
        await session.send_packet(packet)

    async def broadcast(self, topic: str, payload: bytes, qos: int = 0):
        for s in list(self.sessions):
            if not s.connected:
                continue
            for pattern, sub_qos in s.subscriptions.items():
                if topic_matches(pattern, topic):
                    eff_qos = min(qos, sub_qos)
                    await self.send_publish(s, topic, payload, qos=eff_qos, retain=False)
                    break

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        session = MQTTClientSession(reader, writer, self)
        self.sessions.add(session)
        peer = writer.get_extra_info("peername")
        logger.debug(f"New socket connection from {peer}")

        try:
            while True:
                header_byte = await reader.read(1)
                if not header_byte:
                    break  # Connection closed
                first_byte = header_byte[0]
                packet_type = (first_byte >> 4) & 0x0F
                flags = first_byte & 0x0F

                rem_len = await decode_remaining_length(reader)
                packet_data = await reader.readexactly(rem_len) if rem_len > 0 else b""

                if packet_type == 1:  # CONNECT
                    await session.handle_connect(flags, packet_data)
                elif packet_type == 3:  # PUBLISH
                    await session.handle_publish(flags, packet_data)
                elif packet_type == 8:  # SUBSCRIBE
                    packet_id = struct.unpack("!H", packet_data[0:2])[0]
                    await session.handle_subscribe(packet_id, packet_data[2:])
                elif packet_type == 10:  # UNSUBSCRIBE
                    packet_id = struct.unpack("!H", packet_data[0:2])[0]
                    await session.handle_unsubscribe(packet_id, packet_data[2:])
                elif packet_type == 12:  # PINGREQ
                    await session.send_packet(bytes([0xD0, 0x00]))
                elif packet_type == 14:  # DISCONNECT
                    session.clean_disconnect = True
                    break
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        except Exception as e:
            logger.error(f"Error handling client {session.client_id}: {e}")
        finally:
            self.sessions.discard(session)
            # If not a clean disconnect and client had a will, publish the will
            if session.connected and not session.clean_disconnect and session.will_topic and session.will_message:
                logger.warning(f"Client {session.client_id} disconnected unexpectedly; triggering LWT to '{session.will_topic}'")
                if session.will_retain:
                    self.retained_messages[session.will_topic] = (session.will_message, session.will_qos)
                    self.save_retained_to_disk()
                await self.broadcast(session.will_topic, session.will_message, qos=session.will_qos)

            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(f"Client disconnected: {session.client_id}")

    async def start(self):
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)
        logger.info(f"MQTT Broker listening on {self.host}:{self.port}")
        async with self.server:
            await self.server.serve_forever()

    def stop(self):
        if self.server:
            self.server.close()
            self.save_retained_to_disk()


if __name__ == "__main__":
    broker = MQTTBroker()
    try:
        asyncio.run(broker.start())
    except KeyboardInterrupt:
        logger.info("Broker stopped by user.")

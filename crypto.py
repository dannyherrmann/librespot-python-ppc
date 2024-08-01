from __future__ import unicode_literals
import re
import struct
import io

class CipherPair:
    __receive_cipher = None
    __receive_nonce = 0
    __send_cipher = None
    __send_nonce = 0

    def __init__(self, send_key, receive_key):
        self.__send_cipher = Shannon()
        self.__send_cipher.key(send_key)
        self.__receive_cipher = Shannon()
        self.__receive_cipher.key(receive_key)

    def send_encoded(self, connection, cmd, payload):
        """
        Send decrypted data to the socket
        :param connection:
        :param cmd:
        :param payload:
        :return:
        """
        self.__send_cipher.nonce(self.__send_nonce)
        self.__send_nonce += 1
        buffer = io.BytesIO()
        buffer.write(cmd)
        buffer.write(struct.pack(">H", len(payload)))
        buffer.write(payload)
        buffer.seek(0)
        contents = self.__send_cipher.encrypt(buffer.read())
        mac = self.__send_cipher.finish(4)
        connection.write(contents)
        connection.write(mac)
        connection.flush()

    def receive_encoded(self, connection):
        """
        Receive and parse decrypted data from the socket
        Args:
            connection: ConnectionHolder
        Return:
            The parsed packet will be returned
        """
        try:
            self.__receive_cipher.nonce(self.__receive_nonce)
            self.__receive_nonce += 1
            header_bytes = self.__receive_cipher.decrypt(connection.read(3))
            cmd = struct.pack(">s", bytes([header_bytes[0]]))
            payload_length = (header_bytes[1] << 8) | (header_bytes[2] & 0xff)
            payload_bytes = self.__receive_cipher.decrypt(
                connection.read(payload_length))
            mac = connection.read(4)
            expected_mac = self.__receive_cipher.finish(4)
            if mac != expected_mac:
                raise RuntimeError()
            return Packet(cmd, payload_bytes)
        except IndexError:
            raise RuntimeError("Failed to receive packet")

class Packet:
    def __init__(self, cmd, payload):
        self.cmd = cmd
        self.payload = payload

    def is_cmd(self, cmd):
        return cmd == self.cmd

    class Type:
        secret_block = "\x02"
        ping = "\x04"
        stream_chunk = "\x08"
        stream_chunk_res = "\x09"
        channel_error = "\x0a"
        channel_abort = "\x0b"
        request_key = "\x0c"
        aes_key = "\x0d"
        aes_key_error = "\x0e"
        image = "\x19"
        country_code = "\x1b"
        pong = "\x49"
        pong_ack = "\x4a"
        pause = "\x4b"
        product_info = "\x50"
        legacy_welcome = "\x69"
        license_version = "\x76"
        login = "\xab"
        ap_welcome = "\xac"
        auth_failure = "\xad"
        mercury_req = "\xb2"
        mercury_sub = "\xb3"
        mercury_unsub = "\xb4"
        mercury_event = "\xb5"
        track_ended_time = "\x82"
        unknown_data_all_zeros = "\x1f"
        preferred_locale = "\x74"
        unknown_0x4f = "\x4f"
        unknown_0x0f = "\x0f"
        unknown_0x10 = "\x10"

        @staticmethod
        def parse(val):
            for cmd in [
                    Packet.Type.__dict__[attr] for attr in Packet.Type.__dict__
                    if re.search("__.+?__", attr) is None
                    and type(Packet.Type.__dict__[attr]) is str
            ]:
                if cmd == val:
                    return cmd
            return None

        @staticmethod
        def for_method(method):
            if method == "SUB":
                return Packet.Type.mercury_sub
            if method == "UNSUB":
                return Packet.Type.mercury_unsub
            return Packet.Type.mercury_req

class Shannon:
    n = 16
    fold = n
    initkonst = 0x6996c53a
    keyp = 13

    def __init__(self):
        self.r = [0 for _ in range(self.n)]
        self.crc = [0 for _ in range(self.n)]
        self.init_r = [0 for _ in range(self.n)]
        self.konst = 0
        self.sbuf = 0
        self.mbuf = 0
        self.nbuf = 0

    def rotl(self, i, distance):
        return ((i << distance) | (i >> (32 - distance))) & 0xffffffff

    def sbox(self, i):
        i ^= self.rotl(i, 5) | self.rotl(i, 7)
        i ^= self.rotl(i, 19) | self.rotl(i, 22)
        return i

    def sbox2(self, i):
        i ^= self.rotl(i, 7) | self.rotl(i, 22)
        i ^= self.rotl(i, 5) | self.rotl(i, 19)
        return i

    def cycle(self):
        t = self.r[12] ^ self.r[13] ^ self.konst
        t = self.sbox(t) ^ self.rotl(self.r[0], 1)
        for i in range(1, self.n):
            self.r[i - 1] = self.r[i]
        self.r[self.n - 1] = t
        t = self.sbox2(self.r[2] ^ self.r[15])
        self.r[0] ^= t
        self.sbuf = t ^ self.r[8] ^ self.r[12]

    def crc_func(self, i):
        t = self.crc[0] ^ self.crc[2] ^ self.crc[15] ^ i
        for j in range(1, self.n):
            self.crc[j - 1] = self.crc[j]
        self.crc[self.n - 1] = t

    def mac_func(self, i):
        self.crc_func(i)
        self.r[self.keyp] ^= i

    def init_state(self):
        self.r[0] = 1
        self.r[1] = 1
        for i in range(2, self.n):
            self.r[i] = self.r[i - 1] + self.r[i - 2]
        self.konst = self.initkonst

    def save_state(self):
        for i in range(self.n):
            self.init_r[i] = self.r[i]

    def reload_state(self):
        for i in range(self.n):
            self.r[i] = self.init_r[i]

    def gen_konst(self):
        self.konst = self.r[0]

    def add_key(self, k):
        self.r[self.keyp] ^= k

    def diffuse(self):
        for _ in range(self.fold):
            self.cycle()

    def load_key(self, key):
        padding_size = int((len(key) + 3) / 4) * 4 - len(key)
        key = key + (b"\x00" * padding_size) + struct.pack("<I", len(key))
        for i in range(0, len(key), 4):
            self.r[self.keyp] = self.r[self.keyp] ^ struct.unpack("<I", key[i: i + 4])[0]
            self.cycle()
        for i in range(self.n):
            self.crc[i] = self.r[i]
        self.diffuse()
        for i in range(self.n):
            self.r[i] ^= self.crc[i]

    def key(self, key):
        self.init_state()
        self.load_key(key)
        self.gen_konst()
        self.save_state()
        self.nbuf = 0

    def nonce(self, nonce):
        if isinstance(nonce, int):
            nonce = bytes(struct.pack(">I", nonce))
        self.reload_state()
        self.konst = self.initkonst
        self.load_key(nonce)
        self.gen_konst()
        self.nbuf = 0

    def encrypt(self, buffer, n=None):
        if n is None:
            return self.encrypt(buffer, len(buffer))
        buffer = bytearray(buffer)
        i = 0
        if self.nbuf != 0:
            while self.nbuf != 0 and n != 0:
                self.mbuf ^= (buffer[i] & 0xff) << (32 - self.nbuf)
                buffer[i] ^= (self.sbuf >> (32 - self.nbuf)) & 0xff
                i += 1
                self.nbuf -= 8
                n -= 1
            if self.nbuf != 0:
                return b""
            self.mac_func(self.mbuf)
        j = n & ~0x03
        while i < j:
            self.cycle()
            t = ((buffer[i + 3] & 0xFF) << 24) | ((buffer[i + 2] & 0xFF) << 16) | ((buffer[i + 1] & 0xFF) << 8) | (buffer[i] & 0xFF)
            self.mac_func(t)
            t ^= self.sbuf
            buffer[i + 3] = (t >> 24) & 0xFF
            buffer[i + 2] = (t >> 16) & 0xFF
            buffer[i + 1] = (t >> 8) & 0xFF
            buffer[i] = t & 0xFF
            i += 4
        n &= 0x03
        if n != 0:
            self.cycle()
            self.mbuf = 0
            self.nbuf = 32
            while self.nbuf != 0 and n != 0:
                self.mbuf ^= (buffer[i] & 0xff) << (32 - self.nbuf)
                buffer[i] ^= (self.sbuf >> (32 - self.nbuf)) & 0xff
                i += 1
                self.nbuf -= 8
                n -= 1
        return bytes(buffer)

    def decrypt(self, buffer, n=None):
        if n is None:
            return self.decrypt(buffer, len(buffer))
        buffer = bytearray(buffer)
        i = 0
        if self.nbuf != 0:
            while self.nbuf != 0 and n != 0:
                buffer[i] ^= (self.sbuf >> (32 - self.nbuf)) & 0xff
                self.mbuf ^= (buffer[i] & 0xff) << (32 - self.nbuf)
                i += 1
                self.nbuf -= 8
                n -= 1
            if self.nbuf != 0:
                return b""
            self.mac_func(self.mbuf)
        j = n & ~0x03
        while i < j:
            self.cycle()
            t = ((buffer[i + 3] & 0xFF) << 24) | ((buffer[i + 2] & 0xFF) << 16) | ((buffer[i + 1] & 0xFF) << 8) | (buffer[i] & 0xFF)
            t ^= self.sbuf
            self.mac_func(t)
            buffer[i + 3] = (t >> 24) & 0xFF
            buffer[i + 2] = (t >> 16) & 0xFF
            buffer[i + 1] = (t >> 8) & 0xFF
            buffer[i] = t & 0xFF
            i += 4
        n &= 0x03
        if n != 0:
            self.cycle()
            self.mbuf = 0
            self.nbuf = 32
            while self.nbuf != 0 and n != 0:
                buffer[i] ^= (self.sbuf >> (32 - self.nbuf)) & 0xff
                self.mbuf ^= (buffer[i] & 0xff) << (32 - self.nbuf)
                i += 1
                self.nbuf -= 8
                n -= 1
        return bytes(buffer)

    def finish(self, n):
        buffer = bytearray(4)
        i = 0
        if self.nbuf != 0:
            self.mac_func(self.mbuf)
        self.cycle()
        self.add_key(self.initkonst ^ (self.nbuf << 3))
        self.nbuf = 0
        for j in range(self.n):
            self.r[j] ^= self.crc[j]
        self.diffuse()
        while n > 0:
            self.cycle()
            if n >= 4:
                buffer[i + 3] = (self.sbuf >> 24) & 0xff
                buffer[i + 2] = (self.sbuf >> 16) & 0xff
                buffer[i + 1] = (self.sbuf >> 8) & 0xff
                buffer[i] = self.sbuf & 0xff
                n -= 4
                i += 4
            else:
                for j in range(n):
                    buffer[i + j] = (self.sbuf >> (i * 8)) & 0xff
                break
        return bytes(buffer)
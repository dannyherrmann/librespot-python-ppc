import util
from crypto import Packet
from metadata_pb2 import AudioFile
from structure import Closeable, PacketsReceiver
import concurrent.futures
import io
import logging
import Queue
import struct
import threading

class ChannelManager(Closeable, PacketsReceiver):
    channels = {}
    chunk_size = 128 * 1024
    executor_service = concurrent.futures.ThreadPoolExecutor()
    logger = logging.getLogger("Librespot:ChannelManager")
    seq_holder = 0
    seq_holder_lock = threading.Condition()
    __session = None

    def __init__(self, session):
        self.__session = session

    def request_chunk(self, file_id, index, file):
        start = int(index * self.chunk_size / 4)
        end = int((index + 1) * self.chunk_size / 4)
        channel = ChannelManager.Channel(self, file, index)
        self.channels[channel.chunk_id] = channel
        out = io.BytesIO()
        out.write(struct.pack(">H", channel.chunk_id))
        out.write(struct.pack(">i", 0x00000000))
        out.write(struct.pack(">i", 0x00000000))
        out.write(struct.pack(">i", 0x00004E20))
        out.write(struct.pack(">i", 0x00030D40))
        out.write(file_id)
        out.write(struct.pack(">i", start))
        out.write(struct.pack(">i", end))
        out.seek(0)
        self.__session.send(Packet.Type.stream_chunk, out.read())

    def dispatch(self, packet):
        payload = io.BytesIO(packet.payload)
        if packet.is_cmd(Packet.Type.stream_chunk_res):
            chunk_id = struct.unpack(">H", payload.read(2))[0]
            channel = self.channels.get(chunk_id)
            if channel is None:
                self.logger.warning(
                    "Couldn't find channel, id: {}, received: {}".format(
                        chunk_id, len(packet.payload)))
                return
            channel.add_to_queue(payload)
        elif packet.is_cmd(Packet.Type.channel_error):
            chunk_id = struct.unpack(">H", payload.read(2))[0]
            channel = self.channels.get(chunk_id)
            if channel is None:
                self.logger.warning(
                    "Dropping channel error, id: {}, code: {}".format(
                        chunk_id,
                        struct.unpack(">H", payload.read(2))[0]))
                return
            channel.stream_error(struct.unpack(">H", payload.read(2))[0])
        else:
            self.logger.warning(
                "Couldn't handle packet, cmd: {}, payload: {}".format(
                    packet.cmd, util.bytes_to_hex(packet.payload)))

    def close(self):
        self.executor_service.shutdown()

    class Channel:
        q = Queue.Queue()
        __buffer = io.BytesIO()
        __header = True

        def __init__(self, channel_manager, file, chunk_index):
            self.channel_manager = channel_manager
            self.__file = file
            self.__chunk_index = chunk_index
            with self.channel_manager.seq_holder_lock:
                self.chunk_id = self.channel_manager.seq_holder
                self.channel_manager.seq_holder += 1
            self.channel_manager.executor_service.submit(
                lambda: ChannelManager.Channel.Handler(self))

        def _handle(self, payload):
            if len(payload) == 0:
                if not self.__header:
                    self.__file.write_chunk(payload, self.__chunk_index, False)
                    return True
                self.channel_manager.logger.debug(
                    "Received empty chunk, skipping.")
                return False
            if self.__header:
                while len(payload.getvalue()) > 0:
                    length = struct.unpack(">H", payload.read(2))[0]
                    if not length > 0:
                        break
                    header_id = struct.unpack(">B", payload.read(1))[0]
                    header_data = payload.read(length - 1)
                    self.__file.write_header(header_id, bytearray(header_data), False)
                self.__header = False
            else:
                self.__buffer.write(payload.read(len(payload.getvalue())))
            return False

        def add_to_queue(self, payload):
            self.q.put(payload)

        def stream_error(self, code):
            self.__file.stream_error(self.__chunk_index, code)

        class Handler:
            def __init__(self, channel):
                self.__channel = channel

            def run(self):
                self.__channel.channel_manager.logger.debug(
                    "ChannelManager.Handler is starting")
                with self.__channel.q.all_tasks_done:
                    self.__channel.channel_manager.channels.pop(
                        self.__channel.chunk_id)
                self.__channel.channel_manager.logger.debug(
                    "ChannelManager.Handler is shutting down")
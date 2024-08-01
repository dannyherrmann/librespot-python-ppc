from __future__ import absolute_import
from crypto import Packet

class AudioDecrypt:
    def decrypt_chunk(self, chunk_index, buffer):
        raise NotImplementedError

    def decrypt_time_ms(self):
        raise NotImplementedError


class AudioQualityPicker:
    def get_file(self, files):
        """
        :param files: List[Metadata.AudioFile]
        :return: Metadata.AudioFile
        """
        raise NotImplementedError

class MessageListener:
    def on_message(self, uri, headers, payload):
        """
        :param uri: str
        :param headers: dict
        :param payload: bytes
        """
        raise NotImplementedError
    
class NoopAudioDecrypt(AudioDecrypt):
    def decrypt_chunk(self, chunk_index, buffer):
        return buffer

    def decrypt_time_ms(self):
        return 0
    
class Closeable:
    def close(self):
        raise NotImplementedError


class FeederException(Exception):
    pass

class PacketsReceiver:
    def dispatch(self, packet):
        raise NotImplementedError
    
class SubListener:
    def event(self, resp):
        raise NotImplementedError

class GeneralAudioStream:
    def stream(self):
        """
        :return: AbsChunkedInputStream
        """
        raise NotImplementedError

    def codec(self):
        """
        :return: SuperAudioFormat
        """
        raise NotImplementedError
    
class GeneralWritableStream:
    def write_chunk(self, buffer, chunk_index, cached):
        raise NotImplementedError
    
class HaltListener:
    def stream_read_halted(self, chunk, _time):
        raise NotImplementedError

    def stream_read_resumed(self, chunk, _time):
        raise NotImplementedError
from .decrypt import AesAudioDecrypt
from .format import SuperAudioFormat
from .storage import ChannelManager
import util
from crypto import Packet
import io
import logging
import random
import time
import urllib
import math
import concurrent.futures
import threading
import struct
import storage_resolve_pb2 as StorageResolve
from structure import PacketsReceiver, Closeable, NoopAudioDecrypt, GeneralAudioStream, GeneralWritableStream, HaltListener, FeederException
import Queue
from metadata import EpisodeId, PlayableId, TrackId
import metadata_pb2 as Metadata

class AbsChunkedInputStream(io.BytesIO, HaltListener):
    chunk_exception = None
    closed = False
    max_chunk_tries = 128
    preload_ahead = 3
    preload_chunk_retries = 2
    retries = []
    retry_on_chunk_error = False
    wait_lock = threading.Condition()
    wait_for_chunk = -1
    __decoded_length = 0
    __mark = 0
    __pos = 0

    def __init__(self, retry_on_chunk_error):
        super(AbsChunkedInputStream, self).__init__()
        self.retries = [0] * self.chunks()
        self.retry_on_chunk_error = retry_on_chunk_error

    def is_closed(self):
        return self.closed

    def buffer(self):
        raise NotImplementedError()

    def size(self):
        raise NotImplementedError()

    def close(self):
        self.closed = True
        with self.wait_lock:
            self.wait_lock.notify_all()

    def available(self):
        return self.size() - self.__pos

    def mark_supported(self):
        return True

    def mark(self, read_ahead_limit):
        self.__mark = self.__pos

    def reset(self):
        self.__pos = self.__mark

    def pos(self):
        return self.__pos

    def seek(self, where, **kwargs):
        if where < 0:
            raise TypeError()
        if self.closed:
            raise IOError("Stream is closed!")
        self.__pos = where
        self.check_availability(int(self.__pos / (128 * 1024)), False, False)

    def skip(self, n):
        if n < 0:
            raise TypeError()
        if self.closed:
            raise IOError("Stream is closed!")
        k = self.size() - self.__pos
        if n < k:
            k = n
        self.__pos += k
        chunk = int(self.__pos / (128 * 1024))
        self.check_availability(chunk, False, False)
        return k

    def requested_chunks(self):
        raise NotImplementedError()

    def available_chunks(self):
        raise NotImplementedError()

    def chunks(self):
        raise NotImplementedError()

    def request_chunk_from_stream(self, index):
        raise NotImplementedError()

    def should_retry(self, chunk):
        if self.retries[chunk] < 1:
            return True
        if self.retries[chunk] > self.max_chunk_tries:
            return False
        return self.retry_on_chunk_error

    def check_availability(self, chunk, wait, halted):
        if halted and not wait:
            raise TypeError()
        if not self.requested_chunks()[chunk]:
            self.request_chunk_from_stream(chunk)
            self.requested_chunks()[chunk] = True
        for i in range(chunk + 1,
                       min(self.chunks() - 1, chunk + self.preload_ahead) + 1):
            if (self.requested_chunks()[i]
                    and self.retries[i] < self.preload_chunk_retries):
                self.request_chunk_from_stream(i)
                self.requested_chunks()[chunk] = True
        if wait:
            if self.available_chunks()[chunk]:
                return
            retry = False
            with self.wait_lock:
                if not halted:
                    self.stream_read_halted(chunk, int(time.time() * 1000))
                self.chunk_exception = None
                self.wait_for_chunk = chunk
                self.wait_lock.wait_for(lambda: self.available_chunks()[chunk])
                if self.closed:
                    return
                if self.chunk_exception is not None:
                    if self.should_retry(chunk):
                        retry = True
                    else:
                        raise AbsChunkedInputStream.ChunkException
                if not retry:
                    self.stream_read_halted(chunk, int(time.time() * 1000))
            if retry:
                time.sleep(math.log10(self.retries[chunk]))
                self.check_availability(chunk, True, True)

    def read(self, __size=0):
        if self.closed:
            raise IOError("Stream is closed!")
        if __size <= 0:
            if self.__pos == self.size():
                return b""
            buffer = io.BytesIO()
            total_size = self.size()
            chunk = int(self.__pos / (128 * 1024))
            chunk_off = int(self.__pos % (128 * 1024))
            chunk_total = int(math.ceil(total_size / (128 * 1024)))
            self.check_availability(chunk, True, False)
            buffer.write(self.buffer()[chunk][chunk_off:])
            chunk += 1
            if chunk != chunk_total:
                while chunk <= chunk_total - 1:
                    self.check_availability(chunk, True, False)
                    buffer.write(self.buffer()[chunk])
                    chunk += 1
            buffer.seek(0)
            self.__pos += buffer.getbuffer().nbytes
            return buffer.read()
        buffer = io.BytesIO()
        chunk = int(self.__pos / (128 * 1024))
        chunk_off = int(self.__pos % (128 * 1024))
        chunk_end = int(__size / (128 * 1024))
        chunk_end_off = int(__size % (128 * 1024))
        if chunk_end > self.size():
            chunk_end = int(self.size() / (128 * 1024))
            chunk_end_off = int(self.size() % (128 * 1024))
        self.check_availability(chunk, True, False)
        if chunk_off + __size > len(self.buffer()[chunk]):
            buffer.write(self.buffer()[chunk][chunk_off:])
            chunk += 1
            while chunk <= chunk_end:
                self.check_availability(chunk, True, False)
                if chunk == chunk_end:
                    buffer.write(self.buffer()[chunk][:chunk_end_off])
                else:
                    buffer.write(self.buffer()[chunk])
                chunk += 1
        else:
            buffer.write(self.buffer()[chunk][chunk_off:chunk_off + __size])
        buffer.seek(0)
        self.__pos += buffer.getbuffer().nbytes
        return buffer.read()

    def notify_chunk_available(self, index):
        self.available_chunks()[index] = True
        self.__decoded_length += len(self.buffer()[index])
        with self.wait_lock:
            if index == self.wait_for_chunk and not self.closed:
                self.wait_for_chunk = -1
                self.wait_lock.notify_all()

    def notify_chunk_error(self, index, ex):
        self.available_chunks()[index] = False
        self.requested_chunks()[index] = False
        self.retries[index] += 1
        with self.wait_lock:
            if index == self.wait_for_chunk and not self.closed:
                self.chunk_exception = ex
                self.wait_for_chunk = -1
                self.wait_lock.notify_all()

    def decoded_length(self):
        return self.__decoded_length

    class ChunkException(IOError):

        @staticmethod
        def from_stream_error(stream_error):
            return AbsChunkedInputStream \
                .ChunkException("Failed due to stream error, code: {}".format(stream_error))

class AudioKeyManager(PacketsReceiver, Closeable):
    audio_key_request_timeout = 20
    logger = logging.getLogger("Librespot:AudioKeyManager")
    __callbacks = {}
    __seq_holder = 0
    __seq_holder_lock = threading.Condition()
    __zero_short = b"\x00\x00"

    def __init__(self, session):
        self.__session = session

    def dispatch(self, packet):
        payload = io.BytesIO(packet.payload)
        seq = struct.unpack(">i", payload.read(4))[0]
        callback = self.__callbacks.get(seq)
        if callback is None:
            self.logger.warning(
                "Couldn't find callback for seq: {}".format(seq))
            return
        if packet.is_cmd(Packet.Type.aes_key):
            key = payload.read(16)
            callback.key(key)
        elif packet.is_cmd(Packet.Type.aes_key_error):
            code = struct.unpack(">H", payload.read(2))[0]
            callback.error(code)
        else:
            self.logger.warning(
                "Couldn't handle packet, cmd: {}, length: {}".format(
                    packet.cmd, len(packet.payload)))

    def get_audio_key(self, gid, file_id, retry=True):
        with self.__seq_holder_lock:
            seq = self.__seq_holder
            self.__seq_holder += 1
        out = io.BytesIO()
        out.write(file_id)
        out.write(gid)
        out.write(struct.pack(">i", seq))
        out.write(self.__zero_short)
        out.seek(0)
        self.__session.send(Packet.Type.request_key, out.read())
        callback = AudioKeyManager.SyncCallback(self)
        self.__callbacks[seq] = callback
        key = callback.wait_response()
        if key is None:
            if retry:
                return self.get_audio_key(gid, file_id, False)
            raise RuntimeError(
                "Failed fetching audio key! gid: {}, fileId: {}".format(
                    util.bytes_to_hex(gid), util.bytes_to_hex(file_id)))
        return key

    class Callback:

        def key(self, key):
            raise NotImplementedError

        def error(self, code):
            raise NotImplementedError

    class SyncCallback(Callback):
        __reference = Queue.Queue()
        __reference_lock = threading.Condition()

        def __init__(self, audio_key_manager):
            self.__audio_key_manager = audio_key_manager

        def key(self, key):
            with self.__reference_lock:
                self.__reference.put(key)
                self.__reference_lock.notify_all()

        def error(self, code):
            self.__audio_key_manager.logger.fatal(
                "Audio key error, code: {}".format(code))
            with self.__reference_lock:
                self.__reference.put(None)
                self.__reference_lock.notify_all()

        def wait_response(self):
            with self.__reference_lock:
                self.__reference_lock.wait(
                    AudioKeyManager.audio_key_request_timeout)
                return self.__reference.get(block=False)

class CdnManager:
    logger = logging.getLogger("Librespot:CdnManager")

    def __init__(self, session):
        self.__session = session

    def get_head(self, file_id):
        response = self.__session.client().get(
            self.__session.get_user_attribute("head-files-url", "https://heads-fa.spotify.com/head/{file_id}")
            .replace("{file_id}", util.bytes_to_hex(file_id))
        )
        if response.status_code != 200:
            raise IOError("{}".format(response.status_code))
        body = response.content
        if body is None:
            raise IOError("Response body is empty!")
        return body

    def stream_external_episode(self, episode, external_url, halt_listener):
        return CdnManager.Streamer(
            self.__session,
            StreamId(episode=episode),
            SuperAudioFormat.MP3,
            CdnManager.CdnUrl(self, None, external_url),
            self.__session.cache(),
            NoopAudioDecrypt(),
            halt_listener,
        )

    def stream_file(self, file, key, url, halt_listener):
        return CdnManager.Streamer(
            self.__session,
            StreamId(file=file),
            SuperAudioFormat.get(file.format),
            CdnManager.CdnUrl(self, file.file_id, url),
            self.__session.cache(),
            AesAudioDecrypt(key),
            halt_listener,
        )

    def get_audio_url(self, file_id):
        response = self.__session.api().send(
            "GET", "/storage-resolve/files/audio/interactive/{}".format(util.bytes_to_hex(file_id)), None, None
        )
        if response.status_code != 200:
            raise IOError(response.status_code)
        body = response.content
        if body is None:
            raise IOError("Response body is empty!")
        proto = StorageResolve.StorageResolveResponse()
        proto.ParseFromString(body)
        if proto.result == StorageResolve.StorageResolveResponse.Result.CDN:
            url = random.choice(proto.cdnurl)
            self.logger.debug("Fetched CDN url for {}: {}".format(util.bytes_to_hex(file_id), url))
            return url
        raise CdnManager.CdnException("Could not retrieve CDN url! result: {}".format(proto.result))

    class CdnException(Exception):
        pass

    class InternalResponse:
        def __init__(self, buffer, headers):
            self.buffer = buffer
            self.headers = headers

    class CdnUrl:
        def __init__(self, cdn_manager, file_id, url):
            self.__cdn_manager = cdn_manager
            self.__file_id = file_id
            self.set_url(url)

        def url(self):
            if self.__expiration == -1:
                return self.url
            if self.__expiration <= int(time.time() * 1000) + 5 * 60 * 1000:
                self.url = self.__cdn_manager.get_audio_url(self.__file_id)
            return self.url

        def set_url(self, url):
            self.url = url
            if self.__file_id is not None:
                token_url = urllib.parse.urlparse(url)
                token_query = urllib.parse.parse_qs(token_url.query)
                token_list = token_query.get("__token__")
                try:
                    token_str = str(token_list[0])
                except TypeError:
                    token_str = ""
                expires_list = token_query.get("Expires")
                try:
                    expires_str = str(expires_list[0])
                except TypeError:
                    expires_str = ""
                if token_str != "None" and len(token_str) != 0:
                    expire_at = None
                    split = token_str.split("~")
                    for s in split:
                        try:
                            i = s.index("=")
                        except ValueError:
                            continue
                        if s[:i] == "exp":
                            expire_at = int(s[i + 1:])
                            break
                    if expire_at is None:
                        self.__expiration = -1
                        self.__cdn_manager.logger.warning("Invalid __token__ in CDN url: {}".format(url))
                        return
                    self.__expiration = expire_at * 1000
                elif expires_str != "None" and len(expires_str) != 0:
                    expires_at = None
                    expires_str = expires_str.split("~")[0]
                    expires_at = int(expires_str)
                    if expires_at is None:
                        self.__expiration = -1
                        self.__cdn_manager.logger.warning("Invalid Expires param in CDN url: {}".format(url))
                        return
                    self.__expiration = expires_at * 1000
                else:
                    try:
                        i = token_url.query.index("_")
                    except ValueError:
                        self.__expiration = -1
                        self.__cdn_manager.logger.warning("Couldn't extract expiration, invalid parameter in CDN url: {}".format(url))
                        return
                    self.__expiration = int(token_url.query[:i]) * 1000
            else:
                self.__expiration = -1

    class Streamer(GeneralAudioStream, GeneralWritableStream):
        executor_service = concurrent.futures.ThreadPoolExecutor()

        def __init__(self, session, stream_id, audio_format, cdn_url, cache, audio_decrypt, halt_listener):
            self.__session = session
            self.__stream_id = stream_id
            self.__audio_format = audio_format
            self.__audio_decrypt = audio_decrypt
            self.__cdn_url = cdn_url
            self.halt_listener = halt_listener
            response = self.request(range_start=0, range_end=ChannelManager.chunk_size - 1)
            content_range = response.headers.get("Content-Range")
            if content_range is None:
                raise IOError("Missing Content-Range header!")
            split = content_range.split("/")
            self.size = int(split[1])
            self.chunks = int(math.ceil(self.size / ChannelManager.chunk_size))
            first_chunk = response.buffer
            self.available = [False for _ in range(self.chunks)]
            self.requested = [False for _ in range(self.chunks)]
            self.buffer = [b"" for _ in range(self.chunks)]
            self.__internal_stream = CdnManager.Streamer.InternalStream(self, False)
            self.requested[0] = True
            self.write_chunk(first_chunk, 0, False)

        def write_chunk(self, chunk, chunk_index, cached):
            if self.__internal_stream.is_closed():
                return
            self.__session.logger.debug(
                "Chunk {}/{} completed, cached: {}, stream: {}".format(chunk_index + 1, self.chunks, cached, self.describe())
            )
            self.buffer[chunk_index] = self.__audio_decrypt.decrypt_chunk(chunk_index, chunk)
            self.__internal_stream.notify_chunk_available(chunk_index)

        def stream(self):
            return self.__internal_stream

        def codec(self):
            return self.__audio_format

        def describe(self):
            if self.__stream_id.is_episode():
                return "episode_gid: {}".format(self.__stream_id.get_episode_gid())
            return "file_id: {}".format(self.__stream_id.get_file_id())

        def decrypt_time_ms(self):
            return self.__audio_decrypt.decrypt_time_ms()

        def request_chunk(self, index):
            response = self.request(index)
            self.write_chunk(response.buffer, index, False)

        def request(self, chunk=None, range_start=None, range_end=None):
            if chunk is None and range_start is None and range_end is None:
                raise TypeError()
            if chunk is not None:
                range_start = ChannelManager.chunk_size * chunk
                range_end = (chunk + 1) * ChannelManager.chunk_size - 1
            response = self.__session.client().get(
                self.__cdn_url.url,
                headers={"Range": "bytes={}-{}".format(range_start, range_end)},
            )
            if response.status_code != 206:
                raise IOError(response.status_code)
            body = response.content
            if body is None:
                raise IOError("Response body is empty!")
            return CdnManager.InternalResponse(body, dict(response.headers))

        class InternalStream(AbsChunkedInputStream):
            def __init__(self, streamer, retry_on_chunk_error):
                self.streamer = streamer
                super(CdnManager.Streamer.InternalStream, self).__init__(retry_on_chunk_error)

            def buffer(self):
                return self.streamer.buffer

            def size(self):
                return self.streamer.size

            def close(self):
                super(CdnManager.Streamer.InternalStream, self).close()
                del self.streamer.buffer

            def requested_chunks(self):
                return self.streamer.requested

            def available_chunks(self):
                return self.streamer.available

            def chunks(self):
                return self.streamer.chunks

            def request_chunk_from_stream(self, index):
                self.streamer.executor_service.submit(lambda: self.streamer.request_chunk(index))

            def stream_read_halted(self, chunk, _time):
                if self.streamer.halt_listener is not None:
                    self.streamer.executor_service.submit(lambda: self.streamer.halt_listener.stream_read_halted(chunk, _time))

            def stream_read_resumed(self, chunk, _time):
                if self.streamer.halt_listener is not None:
                    self.streamer.executor_service.submit(lambda: self.streamer.halt_listener.stream_read_resumed(chunk, _time))

class PlayableContentFeeder:
    logger = logging.getLogger("Librespot:PlayableContentFeeder")
    storage_resolve_interactive = "/storage-resolve/files/audio/interactive/{}"
    storage_resolve_interactive_prefetch = "/storage-resolve/files/audio/interactive_prefetch/{}"

    def __init__(self, session):
        self.__session = session

    def load(self, playable_id, audio_quality_picker, preload, halt_listener):
        if isinstance(playable_id, TrackId):
            return self.load_track(playable_id, audio_quality_picker, preload, halt_listener)
        if isinstance(playable_id, EpisodeId):
            return self.load_episode(playable_id, audio_quality_picker, preload, halt_listener)
        raise TypeError("Unknown content: {}".format(playable_id))

    def load_stream(self, file, track, episode, preload, halt_lister):
        if track is None and episode is None:
            raise RuntimeError()
        response = self.resolve_storage_interactive(file.file_id, preload)
        if response.result == StorageResolve.StorageResolveResponse.Result.CDN:
            if track is not None:
                return CdnFeedHelper.load_track(self.__session, track, file, response, preload, halt_lister)
            return CdnFeedHelper.load_episode(self.__session, episode, file, response, preload, halt_lister)
        if response.result == StorageResolve.StorageResolveResponse.Result.STORAGE:
            if track is None:
                pass
        elif response.result == StorageResolve.StorageResolveResponse.Result.RESTRICTED:
            raise RuntimeError("Content is restricted!")
        elif response.result == StorageResolve.StorageResolveResponse.Response.UNRECOGNIZED:
            raise RuntimeError("Content is unrecognized!")
        else:
            raise RuntimeError("Unknown result: {}".format(response.result))

    def load_episode(self, episode_id, audio_quality_picker, preload, halt_listener):
        episode = self.__session.api().get_metadata_4_episode(episode_id)
        if episode.external_url:
            return CdnFeedHelper.load_episode_external(self.__session, episode, halt_listener)
        file = audio_quality_picker.get_file(episode.audio)
        if file is None:
            self.logger.fatal("Couldn't find any suitable audio file, available: {}".format(episode.audio))
        return self.load_stream(file, None, episode, preload, halt_listener)

    def load_track(self, track_id_or_track, audio_quality_picker, preload, halt_listener):
        if isinstance(track_id_or_track, TrackId):
            original = self.__session.api().get_metadata_4_track(track_id_or_track)
            track = self.pick_alternative_if_necessary(original)
            if track is None:
                raise RuntimeError("Cannot get alternative track")
        else:
            track = track_id_or_track
        file = audio_quality_picker.get_file(track.file)
        if file is None:
            self.logger.fatal("Couldn't find any suitable audio file, available: {}".format(track.file))
            raise FeederException()
        return self.load_stream(file, track, None, preload, halt_listener)

    def pick_alternative_if_necessary(self, track):
        if len(track.file) > 0:
            return track
        for alt in track.alternative:
            if len(alt.file) > 0:
                return Metadata.Track(
                    gid=track.gid,
                    name=track.name,
                    album=track.album,
                    artist=track.artist,
                    number=track.number,
                    disc_number=track.disc_number,
                    duration=track.duration,
                    popularity=track.popularity,
                    explicit=track.explicit,
                    external_id=track.external_id,
                    restriction=track.restriction,
                    file=alt.file,
                    sale_period=track.sale_period,
                    preview=track.preview,
                    tags=track.tags,
                    earliest_live_timestamp=track.earliest_live_timestamp,
                    has_lyrics=track.has_lyrics,
                    availability=track.availability,
                    licensor=track.licensor)
        return None

    def resolve_storage_interactive(self, file_id, preload):
        resp = self.__session.api().send(
            "GET",
            (self.storage_resolve_interactive_prefetch if preload else self.storage_resolve_interactive).format(util.bytes_to_hex(file_id)),
            None,
            None,
        )
        if resp.status_code != 200:
            raise RuntimeError(resp.status_code)
        body = resp.content
        if body is None:
            raise RuntimeError("Response body is empty!")
        storage_resolve_response = StorageResolve.StorageResolveResponse()
        storage_resolve_response.ParseFromString(body)
        return storage_resolve_response

    class LoadedStream:
        def __init__(self, track_or_episode, input_stream, normalization_data, metrics):
            if isinstance(track_or_episode, Metadata.Track):
                self.track = track_or_episode
                self.episode = None
            elif isinstance(track_or_episode, Metadata.Episode):
                self.track = None
                self.episode = track_or_episode
            else:
                raise TypeError()
            self.input_stream = input_stream
            self.normalization_data = normalization_data
            self.metrics = metrics

    class Metrics:
        def __init__(self, file_id, preloaded_audio_key, audio_key_time):
            self.file_id = None if file_id is None else util.bytes_to_hex(file_id)
            self.preloaded_audio_key = preloaded_audio_key
            self.audio_key_time = audio_key_time
            if preloaded_audio_key and audio_key_time != -1:
                raise RuntimeError()

class StreamId:
    def __init__(self, file=None, episode=None):
        if file is None and episode is None:
            return
        self.file_id = None if file is None else file.file_id
        self.episode_gid = None if episode is None else episode.gid

    def get_file_id(self):
        if self.file_id is None:
            raise RuntimeError("Not a file!")
        return util.bytes_to_hex(self.file_id)

    def is_episode(self):
        return self.episode_gid is not None

    def get_episode_gid(self):
        if self.episode_gid is None:
            raise RuntimeError("Not an episode!")
        return util.bytes_to_hex(self.episode_gid)
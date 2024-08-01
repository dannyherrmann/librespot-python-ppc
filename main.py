
from __future__ import unicode_literals
from Crypto.Util.number import getRandomNBitInteger, long_to_bytes
from Crypto.Random import get_random_bytes
from Crypto import Random
from Crypto.PublicKey import RSA
from Crypto.Hash import SHA1
from Crypto.Hash import HMAC
from Crypto.Signature import PKCS1_v1_5
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Cipher import AES
import packet
import requests
import random
from enum import Enum
import platform
import socket
import websocket
import os
import io
import json
import util
import struct
import keyexchange_pb2 as Keyexchange
from keyexchange_pb2 import BuildInfo, Platform, Product, ProductFlags
from structure import Closeable, MessageListener, SubListener
from audio import AudioKeyManager
import logging
import metadata_pb2 as Metadata
import playlist4_external_pb2 as Playlist4External
import client_token_pb2 as ClientToken
from mercury import MercuryRequests, RawMercuryRequest, MercuryClient
import connectivity_pb2 as Connectivity
import threading
import sched
import concurrent.futures
import base64
import gzip
import time
from audio.storage import ChannelManager
from audio import CdnManager
from audio import PlayableContentFeeder
from cache import CacheManager
import urllib
from crypto import CipherPair, Packet
import binascii
from explicit_content_pubsub_pb2 import UserAttributesUpdate
import defusedxml.ElementTree
import authentication_pb2 as Authentication
import connect_pb2 as Connect

logging.basicConfig(level=logging.DEBUG)

class ApiClient(Closeable):
    logger = logging.getLogger("Librespot:ApiClient")
    __base_url = None
    __client_token_str = None
    __session = None
    
    def __init__(self, session):
        self.__session = session
        self.__base_url = "https://%s" % ApResolver.get_random_spclient()
        
    def build_request(self, method, suffix, headers, body):
        if self.__client_token is None:
            resp = self.__client_token_str = resp.granted_token.token
            self.logger.debug("Updated client token: {}".format(self.__client_token_str))
            
        request = request.PreparedRequest()
        request.method = method
        request.data = body
        request.headers = {}
        if headers is not None:
            request.headers = headers
        request.headers["Authorization"] = "Bearer {}".format(self.__session.tokens().get("playlist-read"))
        request.headers["client-token"] = self.__client_token_str
        request.url = self.__base_url + suffix
        return request
    
    def send(self, method, suffix, headers, body):
        """
        Send a request.

        :param method: str: HTTP method (e.g., 'GET', 'POST')
        :param suffix: str: URL suffix to append to the base URL
        :param headers: dict or None: Optional headers to include in the request
        :param body: bytes or None: Optional body to include in the request
        :return: requests.Response: The response object
        """
        response = self.__session.client().send(
            self.build_request(method, suffix, headers, body)
        )
        return response
    
    def put_connect_state(self, connection_id, proto):
        """
        Send a PUT request to update the connect state.

        :param connection_id: str: The connection ID
        :param proto: Connect.PutStateRequest: The protobuf state request
        """
        response = self.send(
            "PUT",
            "/connect-state/v1/devices/{}".format(self.__session.device_id()),
            {
                "Content-Type": "application/protobuf",
                "X-Spotify-Connection-Id": connection_id,
            },
            proto.SerializeToString(),
        )
        if response.status_code == 413:
            self.logger.warning(
                "PUT state payload is too large: {} bytes uncompressed.".
                format(len(proto.SerializeToString())))
        elif response.status_code != 200:
            self.logger.warning("PUT state returned {}. headers: {}".format(
                response.status_code, response.headers))
    
    def get_metadata_4_track(self, track):
        """
        Get metadata for a track.

        :param track: TrackId
        """
        response = self.send("GET",
                            "/metadata/4/track/{}".format(track.hex_id()),
                            None, None)
        ApiClient.StatusCodeException.check_status(response)
        body = response.content
        if body is None:
            raise RuntimeError()
        proto = Metadata.Track()
        proto.ParseFromString(body)
        return proto
    
    def get_metadata_4_episode(self, episode):
        """
        Get metadata for an episode.

        :param episode: EpisodeId
        """
        response = self.send("GET",
                            "/metadata/4/episode/{}".format(episode.hex_id()),
                            None, None)
        ApiClient.StatusCodeException.check_status(response)
        body = response.content
        if body is None:
            raise RuntimeError()
        proto = Metadata.Episode()
        proto.ParseFromString(body)
        return proto
    
    def get_metadata_4_album(self, album):
        """
        Get metadata for an album.

        :param album: AlbumId
        """
        response = self.send("GET",
                            "/metadata/4/album/{}".format(album.hex_id()),
                            None, None)
        ApiClient.StatusCodeException.check_status(response)
        body = response.content
        if body is None:
            raise RuntimeError()
        proto = Metadata.Album()
        proto.ParseFromString(body)
        return proto
    
    def get_metadata_4_artist(self, artist):
        """
        Get metadata for an artist.

        :param artist: ArtistId
        """
        response = self.send("GET",
                            "/metadata/4/artist/{}".format(artist.hex_id()),
                            None, None)
        ApiClient.StatusCodeException.check_status(response)
        body = response.content
        if body is None:
            raise RuntimeError()
        proto = Metadata.Artist()
        proto.ParseFromString(body)
        return proto
    
    def get_metadata_4_show(self, show):
        """
        Get metadata for a show.

        :param show: ShowId
        """
        response = self.send("GET",
                            "/metadata/4/show/{}".format(show.hex_id()),
                            None, None)
        ApiClient.StatusCodeException.check_status(response)
        body = response.content
        if body is None:
            raise RuntimeError()
        proto = Metadata.Show()
        proto.ParseFromString(body)
        return proto
    
    def get_playlist(self, _id):
        """
        Get a playlist.

        :param _id: PlaylistId
        """
        response = self.send("GET",
                            "/playlist/v2/playlist/{}".format(_id.id()),
                            None, None)
        ApiClient.StatusCodeException.check_status(response)
        body = response.content
        if body is None:
            raise RuntimeError()
        proto = Playlist4External.SelectedListContent()
        proto.ParseFromString(body)
        return proto
    
    def set_client_token(self, client_token):
        self.__client_token_str = client_token
        
    def __client_token(self):
        proto_req = ClientToken.ClientTokenRequest(
            request_type=ClientToken.ClientTokenRequestType.REQUEST_CLIENT_DATA_REQUEST,
            client_data=ClientToken.ClientDataRequest(
                client_id=MercuryRequests.keymaster_client_id,
                client_version=Version.version_name,
                connectivity_sdk_data=Connectivity.ConnectivitySdkData(
                    device_id=self.__session.device_id(),
                    platform_specific_data=Connectivity.PlatformSpecificData(
                        windows=Connectivity.NativeWindowsData(
                            something1=10,
                            something3=21370,
                            something4=2,
                            something6=9,
                            something7=332,
                            something8=33404,
                            something10=True,
                        ),
                    ),
                ),
            ),
        )

        resp = requests.post(
            "https://clienttoken.spotify.com/v1/clienttoken",
            proto_req.SerializeToString(),
            headers={
                "Accept": "application/x-protobuf",
                "Content-Encoding": "",
            },
        )

        ApiClient.StatusCodeException.check_status(resp)

        proto_resp = ClientToken.ClientTokenResponse()
        proto_resp.ParseFromString(resp.content)
        return proto_resp
    
    class StatusCodeException(IOError):
        """ """
        def __init__(self, response):
            super().__init__(response.status_code)
            self.code = response.status_code

        @staticmethod
        def check_status(response):
            """
            :param response: requests.Response:
            """
            if response.status_code != 200:
                raise ApiClient.StatusCodeException(response)
            
class ApResolver:
    """ """
    base_url = "https://apresolve.spotify.com/"

    @staticmethod
    def request(service_type):
        """Gets the specified ApResolve

        :param service_type: str:
        :returns: The resulting object will be returned

        """
        response = requests.get("{}?type={}".format(ApResolver.base_url, service_type))
        if response.status_code != 200:
            if response.status_code == 502:
                raise RuntimeError(
                    "ApResolve request failed with the following return value: {}. Servers might be down!".format(response.content)
                )
        return response.json()

    @staticmethod
    def get_random_of(service_type):
        """Gets the specified random ApResolve url

        :param service_type: str:
        :returns: A random ApResolve url will be returned

        """
        pool = ApResolver.request(service_type)
        urls = pool.get(service_type)
        if urls is None or len(urls) == 0:
            raise RuntimeError("No ApResolve url available")
        return random.choice(urls)

    @staticmethod
    def get_random_dealer():
        """Get dealer endpoint url

        :returns: dealer endpoint url

        """
        return ApResolver.get_random_of("dealer")

    @staticmethod
    def get_random_spclient():
        """Get spclient endpoint url

        :returns: spclient endpoint url

        """
        return ApResolver.get_random_of("spclient")

    @staticmethod
    def get_random_accesspoint():
        """Get accesspoint endpoint url

        :returns: accesspoint endpoint url

        """
        return ApResolver.get_random_of("accesspoint")
    
class DealerClient(Closeable):
    """ """
    logger = logging.getLogger("Librespot:DealerClient")
    __connection = None  # typing.Union[ConnectionHolder, None]
    __last_scheduled_reconnection = None  # typing.Union[sched.Event, None]
    __message_listeners = {}  # typing.Dict[MessageListener, typing.List[str]]
    __message_listeners_lock = threading.Condition()
    __request_listeners = {}  # typing.Dict[str, RequestListener]
    __request_listeners_lock = threading.Condition()
    __scheduler = sched.scheduler(time.time, time.sleep)
    __session = None  # Session
    __worker = concurrent.futures.ThreadPoolExecutor()

    def __init__(self, session):
        self.__session = session
        
    def add_message_listener(self, listener, uris):
        """
        :param listener: MessageListener:
        :param uris: list[str]:
        """
        with self.__message_listeners_lock:
            if listener in self.__message_listeners:
                raise TypeError(
                    "A listener for {} has already been added.".format(uris))
            self.__message_listeners[listener] = uris
            self.__message_listeners_lock.notify_all()
            
    def add_request_listener(self, listener, uri):
        """
        :param listener: RequestListener:
        :param uri: str:
        """
        with self.__request_listeners_lock:
            if uri in self.__request_listeners:
                raise TypeError(
                    "A listener for '{}' has already been added.".format(uri))
            self.__request_listeners[uri] = listener
            self.__request_listeners_lock.notify_all()
            
    def close(self):
        self.__worker.shutdown()
        
    def connect(self):
        """ """
        self.__connection = DealerClient.ConnectionHolder(
            self.__session,
            self,
            "wss://{}/?access_token={}".format(
                ApResolver.get_random_dealer(),
                self.__session.tokens().get("playlist-read"),
            ),
        )
        
    def connection_invalided(self):
        """ """
        self.__connection = None
        self.logger.debug("Scheduled reconnection attempt in 10 seconds...")

        def anonymous():
            """ """
            self.__last_scheduled_reconnection = None
            self.connect()

        self.__last_scheduled_reconnection = self.__scheduler.enter(
            10, 1, anonymous)
        
    def handle_message(self, obj):
        """
        :param obj: typing.Any:
        """
        uri = obj.get("uri")
        headers = self.__get_headers(obj)
        payloads = obj.get("payloads")
        if payloads is not None:
            if headers.get("Content-Type") == "application/json":
                decoded_payloads = payloads
            elif headers.get("Content-Type") == "plain/text":
                decoded_payloads = payloads
            else:
                decoded_payloads = base64.b64decode(payloads)
                if headers.get("Transfer-Encoding") == "gzip":
                    decoded_payloads = gzip.decompress(decoded_payloads)
        else:
            decoded_payloads = b""
        interesting = False
        with self.__message_listeners_lock:
            for listener in self.__message_listeners:
                dispatched = False
                keys = self.__message_listeners.get(listener)
                for key in keys:
                    if uri.startswith(key) and not dispatched:
                        interesting = True

                        def anonymous():
                            """ """
                            listener.on_message(uri, headers, decoded_payloads)

                        self.__worker.submit(anonymous)
                        dispatched = True
        if not interesting:
            self.logger.debug("Couldn't dispatch message: {}".format(uri))
            
    def handle_request(self, obj):
        """
        :param obj: typing.Any:
        """
        mid = obj.get("message_ident")
        key = obj.get("key")
        headers = self.__get_headers(obj)
        payload = obj.get("payload")
        if headers.get("Transfer-Encoding") == "gzip":
            gz = base64.b64decode(payload.get("compressed"))
            payload = json.loads(gzip.decompress(gz))
        pid = payload.get("message_id")
        sender = payload.get("sent_by_device_id")
        command = payload.get("command")
        self.logger.debug(
            "Received request. [mid: {}, key: {}, pid: {}, sender: {}, command: {}]"
            .format(mid, key, pid, sender, command))
        interesting = False
        with self.__request_listeners_lock:
            for mid_prefix in self.__request_listeners:
                if mid.startswith(mid_prefix):
                    listener = self.__request_listeners.get(mid_prefix)
                    interesting = True

                    def anonymous():
                        """ """
                        result = listener.on_request(mid, pid, sender, command)
                        if self.__connection is not None:
                            self.__connection.send_reply(key, result)
                        self.logger.warning(
                            "Handled request. [key: {}, result: {}]".format(
                                key, result))

                    self.__worker.submit(anonymous)
        if not interesting:
            self.logger.debug("Couldn't dispatch request: {}".format(mid))
            
    def remove_message_listener(self, listener):
        """
        :param listener: MessageListener:
        """
        with self.__message_listeners_lock:
            self.__message_listeners.pop(listener)
            
    def remove_request_listener(self, listener):
        """
        :param listener: RequestListener:
        """
        with self.__request_listeners_lock:
            request_listeners = {}
            for key, value in self.__request_listeners.items():
                if value != listener:
                    request_listeners[key] = value
            self.__request_listeners = request_listeners
            
    def wait_for_listener(self):
        """ """
        with self.__message_listeners_lock:
            if self.__message_listeners == {}:
                return
            self.__message_listeners_lock.wait()
            
    def __get_headers(self, obj):
        headers = obj.get("headers")
        if headers is None:
            return {}
        return headers
    
    class ConnectionHolder(Closeable):
        """ """
        __closed = False
        __dealer_client = None
        __last_scheduled_ping = None
        __received_pong = False
        __scheduler = sched.scheduler(time.time, time.sleep)
        __session = None
        __url = ""
        __ws = None

        def __init__(self, session, dealer_client, url):
            self.__session = session
            self.__dealer_client = dealer_client
            self.__url = url
            self.__ws = websocket.WebSocketApp(url)
                
        def on_failure(self, ws, error):
            """
            :param ws: websocket.WebSocketApp:
            :param error:
            """
            if self.__closed:
                return
            self.__dealer_client.logger.warning(
                "An exception occurred. Reconnecting...")
            self.close()
            
        def on_message(self, ws, text):
            """
            :param ws: websocket.WebSocketApp:
            :param text: str:
            """
            obj = json.loads(text)
            self.__dealer_client.wait_for_listener()
            typ = MessageType.parse(obj.get("type"))
            if typ == MessageType.MESSAGE:
                self.__dealer_client.handle_message(obj)
            elif typ == MessageType.REQUEST:
                self.__dealer_client.handle_request(obj)
            elif typ == MessageType.PONG:
                self.__received_pong = True
            elif typ == MessageType.PING:
                pass
            else:
                raise RuntimeError("Unknown message type for {}".format(typ.value))
            
        def on_open(self, ws):
            """
            :param ws: websocket.WebSocketApp:
            """
            if self.__closed:
                self.__dealer_client.logger.fatal(
                    "I wonder what happened here... Terminating. [closed: {}]".
                    format(self.__closed))
            self.__dealer_client.logger.debug(
                "Dealer connected! [url: {}]".format(self.__url))

            def anonymous():
                """ """
                self.send_ping()
                self.__received_pong = False

                def anonymous2():
                    """ """
                    if self.__last_scheduled_ping is None:
                        return
                    if not self.__received_pong:
                        self.__dealer_client.logger.warning(
                            "Did not receive ping in 3 seconds. Reconnecting..."
                        )
                        self.close()
                        return
                    self.__received_pong = False

                self.__scheduler.enter(3, 1, anonymous2)
                self.__last_scheduled_ping = self.__scheduler.enter(
                    30, 1, anonymous)

            self.__last_scheduled_ping = self.__scheduler.enter(
                30, 1, anonymous)
            
        def send_ping(self):
            """ """
            self.__ws.send('{"type":"ping"}')
            
        def send_reply(self, key, result):
            """
            :param key: str:
            :param result: DealerClient.RequestResult:
            """
            success = ("true" if result == DealerClient.RequestResult.SUCCESS
                    else "false")
            self.__ws.send(
                '{"type":"reply","key":"%s","payload":{"success":%s}}' %
                (key, success))
            
    class RequestResult(Enum):
        """ """
        UNKNOWN_SEND_COMMAND_RESULT = 0
        SUCCESS = 1
        DEVICE_NOT_FOUND = 2
        CONTEXT_PLAYER_ERROR = 3
        DEVICE_DISAPPEARED = 4
        UPSTREAM_ERROR = 5
        DEVICE_DOES_NOT_SUPPORT_COMMAND = 6
        RATE_LIMITED = 7

class EventService(Closeable):
    """ """
    logger = logging.getLogger("Librespot:EventService")
    __worker = concurrent.futures.ThreadPoolExecutor()

    def __init__(self, session):
        self.__session = session

    def __worker_callback(self, event_builder):
        try:
            body = event_builder.to_array()
            resp = self.__session.mercury().send_sync(
                RawMercuryRequest.Builder().set_uri(
                    "hm://event-service/v1/events").set_method("POST").
                add_user_field("Accept-Language", "en").add_user_field(
                    "X-ClientTimeStamp",
                    int(time.time() * 1000)).add_payload_part(body).build())
            self.logger.debug("Event sent. body: {}, result: {}".format(
                body, resp.status_code))
        except IOError as ex:
            self.logger.error("Failed sending event: {} {}".format(
                event_builder, ex))

    def send_event(self, event_or_builder):
        """
        :param event_or_builder: typing.Union[GenericEvent, EventBuilder]:
        """
        if isinstance(event_or_builder, EventService.GenericEvent):
            builder = event_or_builder.build()
        elif isinstance(event_or_builder, EventService.EventBuilder):
            builder = event_or_builder
        else:
            raise TypeError()
        self.__worker.submit(lambda: self.__worker_callback(builder))

    def language(self, lang):
        """
        :param lang: str:
        """
        event = EventService.EventBuilder(EventService.Type.LANGUAGE)
        event.append(s=lang)

    def close(self):
        """ """
        self.__worker.shutdown()

    class Type(Enum):
        """ """
        LANGUAGE = ("812", 1)
        FETCHED_FILE_ID = ("274", 3)
        NEW_SESSION_ID = ("557", 3)
        NEW_PLAYBACK_ID = ("558", 1)
        TRACK_PLAYED = ("372", 1)
        TRACK_TRANSITION = ("12", 37)
        CDN_REQUEST = ("10", 20)

        def __init__(self, event_id, unknown):
            self.eventId = event_id
            self.unknown = unknown

    class GenericEvent:
        """ """

        def build(self):
            """ """
            raise NotImplementedError

    class EventBuilder:
        """ """

        def __init__(self, event_type):
            self.body = io.BytesIO()
            self.append_no_delimiter(event_type.value[0])
            self.append(event_type.value[1])

        def append_no_delimiter(self, s=None):
            """
            :param s: str:  (Default value = None)
            """
            if s is None:
                s = ""
            self.body.write(s.encode())

        def append(self, c=None, s=None):
            """
            :param c: int:  (Default value = None)
            :param s: str:  (Default value = None)
            """
            if c is None and s is None or c is not None and s is not None:
                raise TypeError()
            if c is not None:
                self.body.write(b"\x09")
                self.body.write(bytes([c]))
                return self
            if s is not None:
                self.body.write(b"\x09")
                self.append_no_delimiter(s)
                return self

        def to_array(self):
            """ """
            pos = self.body.tell()
            self.body.seek(0)
            data = self.body.read()
            self.body.seek(pos)
            return data

class MessageType(Enum):
    """ """
    MESSAGE = "message"
    PING = "ping"
    PONG = "pong"
    REQUEST = "request"

    @staticmethod
    def parse(_typ):
        """
        :param _typ: str:
        """
        if _typ == MessageType.MESSAGE.value:
            return MessageType.MESSAGE
        if _typ == MessageType.PING.value:
            return MessageType.PING
        if _typ == MessageType.PONG.value:
            return MessageType.PONG
        if (_typ == MessageType.REQUEST.value):
            return MessageType.REQUEST
        raise TypeError("Unknown MessageType: {}".format(_typ))

class Session(Closeable, MessageListener, SubListener):
    """ """
    cipher_pair = None
    country_code = "EN"
    connection = None
    logger = logging.getLogger("Librespot:Session")
    scheduled_reconnect = None
    scheduler = sched.scheduler(time.time, time.sleep)
    __api = None
    __ap_welcome = None
    __audio_key_manager = None
    __auth_lock = threading.Condition()
    __auth_lock_bool = False
    __cache_manager = None
    __cdn_manager = None
    __channel_manager = None
    __client = None
    __closed = False
    __closing = False
    __content_feeder = None
    __dealer_client = None
    __event_service = None
    __keys = None
    __mercury_client = None
    __receiver = None
    __search = None
    __server_key = (b"\xac\xe0F\x0b\xff\xc20\xaf\xf4k\xfe\xc3\xbf\xbf\x86="
                    b"\xa1\x91\xc6\xcc3l\x93\xa1O\xb3\xb0\x16\x12\xac\xacj"
                    b"\xf1\x80\xe7\xf6\x14\xd9B\x9d\xbe.4fC\xe3b\xd22z\x1a"
                    b"\r\x92;\xae\xdd\x14\x02\xb1\x81U\x05a\x04\xd5,\x96\xa4"
                    b"L\x1e\xcc\x02J\xd4\xb2\x0c\x00\x1f\x17\xed\xc2/\xc45"
                    b"!\xc8\xf0\xcb\xae\xd2\xad\xd7+\x0f\x9d\xb3\xc52\x1a*"
                    b"\xfeY\xf3Z\r\xach\xf1\xfab\x1e\xfb,\x8d\x0c\xb79-\x92"
                    b"G\xe3\xd75\x1am\xbd$\xc2\xae%[\x88\xff\xabs)\x8a\x0b"
                    b"\xcc\xcd\x0cXg1\x89\xe8\xbd4\x80xJ_\xc9k\x89\x9d\x95k"
                    b"\xfc\x86\xd7O3\xa6x\x17\x96\xc9\xc3-\r2\xa5\xab\xcd\x05'"
                    b"\xe2\xf7\x10\xa3\x96\x13\xc4/\x99\xc0'\xbf\xed\x04\x9c"
                    b"<'X\x04\xb6\xb2\x19\xf9\xc1/\x02\xe9Hc\xec\xa1\xb6B\xa0"
                    b"9dH%\xf8\xb3\x9d\xd0\xe8j\xf9HM\xa1\xc2\xba\x860B\xea"
                    b"\x9d\xb3\x08l\x19\x0eH\xb3\x9df\xeb\x00\x06\xa2Z\xee\xa1"
                    b"\x1b\x13\x87<\xd7\x19\xe6U\xbd")
    __stored_str = ""
    __token_provider = None
    __user_attributes = {}
        
    def __init__(self, inner, address):
        self.__client = Session.create_client(inner.conf)
        self.connection = Session.ConnectionHolder.create(address, None)
        self.__inner = inner
        self.__keys = DiffieHellman()
        self.logger.info("Created new session! device_id: {}, ap: {}".format(
            inner.device_id, address))
            
    def api(self):
        """ """
        self.__wait_auth_lock()
        if self.__api is None:
            raise RuntimeError("Session isn't authenticated!")
        return self.__api
    
    def ap_welcome(self):
        """ """
        self.__wait_auth_lock()
        if self.__ap_welcome is None:
            raise RuntimeError("Session isn't authenticated!")
        return self.__ap_welcome
    
    def audio_key(self):
        """ """
        self.__wait_auth_lock()
        if self.__audio_key_manager is None:
            raise RuntimeError("Session isn't authenticated!")
        return self.__audio_key_manager
    
    def authenticate(self, credential):
        """Log in to Spotify

        :param credential: Spotify account login information
        :param credential: Authentication.LoginCredentials:

        """
        self.__authenticate_partial(credential, False)
        with self.__auth_lock:
            self.__mercury_client = MercuryClient(self)
            self.__token_provider = TokenProvider(self)
            self.__audio_key_manager = AudioKeyManager(self)
            self.__channel_manager = ChannelManager(self)
            self.__api = ApiClient(self)
            self.__cdn_manager = CdnManager(self)
            self.__content_feeder = PlayableContentFeeder(self)
            self.__cache_manager = CacheManager(self)
            self.__dealer_client = DealerClient(self)
            self.__search = SearchManager(self)
            self.__event_service = EventService(self)
            self.__auth_lock_bool = False
            self.__auth_lock.notify_all()
        self.dealer().connect()
        self.logger.info("Authenticated as {}!".format(
            self.__ap_welcome.canonical_username))
        self.mercury().interested_in("spotify:user:attributes:update", self)
        self.dealer().add_message_listener(
            self, ["hm://connect-state/v1/connect/logout"])
        
    def cache(self):
        """ """
        self.__wait_auth_lock()
        if self.__cache_manager is None:
            raise RuntimeError("Session isn't authenticated!")
        return self.__cache_manager
    
    def cdn(self):
        """ """
        self.__wait_auth_lock()
        if self.__cdn_manager is None:
            raise RuntimeError("Session isn't authenticated!")
        return self.__cdn_manager
    
    def channel(self):
        """ """
        self.__wait_auth_lock()
        if self.__channel_manager is None:
            raise RuntimeError("Session isn't authenticated!")
        return self.__channel_manager
    
    def client(self):
        """ """
        return self.__client
    
    def close(self):
        """Close instance"""
        self.logger.info("Closing session. device_id: {}".format(
            self.__inner.device_id))
        self.__closing = True
        if self.__dealer_client is not None:
            self.__dealer_client.close()
            self.__dealer_client = None
        if self.__audio_key_manager is not None:
            self.__audio_key_manager = None
        if self.__channel_manager is not None:
            self.__channel_manager.close()
            self.__channel_manager = None
        if self.__event_service is not None:
            self.__event_service.close()
            self.__event_service = None
        if self.__receiver is not None:
            self.__receiver.stop()
            self.__receiver = None
        if self.__client is not None:
            self.__client.close()
            self.__client = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        with self.__auth_lock:
            self.__ap_welcome = None
            self.cipher_pair = None
            self.__closed = True
        self.logger.info("Closed session. device_id: {}".format(
            self.__inner.device_id))

    def connect(self):
        """Connect to the Spotify Server"""
        self.logger.debug("connecting to Spotify Server...")
        acc = Session.Accumulator()
        self.logger.debug("921")
        # Send ClientHello
        nonce = get_random_bytes(0x10)
        self.logger.debug("924")
        client_hello_proto = Keyexchange.ClientHello(
            build_info=Version.standard_build_info(),
            client_nonce=nonce,
            cryptosuites_supported=[
                Keyexchange.Cryptosuite.CRYPTO_SUITE_SHANNON
            ],
            login_crypto_hello=Keyexchange.LoginCryptoHelloUnion(
                diffie_hellman=Keyexchange.LoginCryptoDiffieHellmanHello(
                    gc=self.__keys.public_key_bytes(), server_keys_known=1), ),
            padding=b'\x1e',
        )
        self.logger.debug("936")
        self.logger.debug("Build Info (Python 2.7): {}".format(client_hello_proto.build_info))
        self.logger.debug("Client Nonce (Python 2.7): {}".format(repr(client_hello_proto.client_nonce)))
        self.logger.debug("Cryptosuites Supported (Python 2.7): {}".format(client_hello_proto.cryptosuites_supported))
        self.logger.debug("Login Crypto Hello (Python 2.7): {}".format(client_hello_proto.login_crypto_hello))
        self.logger.debug("Padding (Python 2.7): {}".format(repr(client_hello_proto.padding)))
        client_hello_bytes = client_hello_proto.SerializeToString()
        self.logger.debug("Client Hello (Python 2.7): {}".format(repr(client_hello_bytes)))
        self.logger.debug("Length (Python 2.7): {}".format(len(client_hello_bytes)))
        self.logger.debug("937")
        self.logger.debug("Writing to connection: %s" % repr(b"\x00\x04"))
        self.connection.write(b"\x00\x04")
        self.logger.debug("940")
        length_to_write = 2 + 4 + len(client_hello_bytes)
        self.logger.debug("Writing to connection: %d" % length_to_write)
        self.connection.write_int(length_to_write)
        self.logger.debug("942")
        self.logger.debug("Writing to connection: %s" % repr(client_hello_bytes))
        self.connection.write(client_hello_bytes)
        self.logger.debug("944")
        self.connection.flush()
        self.logger.debug("946")
        self.logger.debug("Writing to acc: %s" % repr(b"\x00\x04"))
        acc.write(b"\x00\x04")
        self.logger.debug("948")
        self.logger.debug("Writing to acc: %d" % length_to_write)
        acc.write_int(length_to_write)
        self.logger.debug("950")
        self.logger.debug("Writing to acc: %s" % repr(client_hello_bytes))
        acc.write(client_hello_bytes)
        self.logger.debug("952")
        # Read APResponseMessage
        ap_response_message_length = self.connection.read_int()
        self.logger.debug("955")
        # Log the length of the response message
        self.logger.debug("Received APResponseMessage length: {}".format(ap_response_message_length))
        acc.write_int(ap_response_message_length)
        ap_response_message_bytes = self.connection.read(
            ap_response_message_length - 4)
        acc.write(ap_response_message_bytes)
        ap_response_message_proto = Keyexchange.APResponseMessage()
        ap_response_message_proto.ParseFromString(ap_response_message_bytes)
        shared_key = util.int_to_bytes(
            self.__keys.compute_shared_key(
                ap_response_message_proto.challenge.login_crypto_challenge.
                diffie_hellman.gs))
        # Check gs_signature
        server_key_int = int(binascii.hexlify(self.__server_key), 16)
        rsa = RSA.construct((server_key_int, 65537))
        pkcs1_v1_5 = PKCS1_v1_5.new(rsa)
        sha1 = SHA1.new()
        sha1.update(ap_response_message_proto.challenge.login_crypto_challenge.
                    diffie_hellman.gs)
        if not pkcs1_v1_5.verify(
                sha1,
                ap_response_message_proto.challenge.login_crypto_challenge.
                diffie_hellman.gs_signature,
        ):
            raise RuntimeError("Failed signature check!")
        # Solve challenge
        buffer = io.BytesIO()
        for i in range(1, 6):
            mac = HMAC.new(shared_key, digestmod=SHA1)
            mac.update(acc.read())
            mac.update(bytes([i]))
            buffer.write(mac.digest())
        buffer.seek(0)
        mac = HMAC.new(buffer.read(20), digestmod=SHA1)
        mac.update(acc.read())
        challenge = mac.digest()
        client_response_plaintext_proto = Keyexchange.ClientResponsePlaintext(
            crypto_response=Keyexchange.CryptoResponseUnion(),
            login_crypto_response=Keyexchange.LoginCryptoResponseUnion(
                diffie_hellman=Keyexchange.LoginCryptoDiffieHellmanResponse(
                    hmac=challenge)),
            pow_response=Keyexchange.PoWResponseUnion(),
        )
        client_response_plaintext_bytes = (
            client_response_plaintext_proto.SerializeToString())
        self.connection.write_int(4 + len(client_response_plaintext_bytes))
        self.connection.write(client_response_plaintext_bytes)
        self.connection.flush()
        try:
            self.connection.set_timeout(1)
            scrap = self.connection.read(4)
            if len(scrap) == 4:
                payload = self.connection.read(
                    struct.unpack(">i", scrap)[0] - 4)
                failed = Keyexchange.APResponseMessage()
                failed.ParseFromString(payload)
                raise RuntimeError(failed)
        except socket.timeout:
            pass
        finally:
            self.connection.set_timeout(0)
        buffer.seek(20)
        with self.__auth_lock:
            self.cipher_pair = CipherPair(buffer.read(32), buffer.read(32))
            self.__auth_lock_bool = True
        self.logger.info("Connection successfully!")
        
    def content_feeder(self):
        """ """
        self.__wait_auth_lock()
        if self.__content_feeder is None:
            raise RuntimeError("Session isn't authenticated!")
        return self.__content_feeder
    
    @staticmethod
    def create_client(conf):
        """
        :param conf: Configuration
        """
        client = requests.Session()
        return client
    
    def dealer(self):
        """ """
        self.__wait_auth_lock()
        if self.__dealer_client is None:
            raise RuntimeError("Session isn't authenticated!")
        return self.__dealer_client
    
    def device_id(self):
        """ """
        return self.__inner.device_id
    
    def device_name(self):
        """ """
        return self.__inner.device_name
    
    def device_type(self):
        """ """
        return self.__inner.device_type
    
    def event(self, resp):
        """
        :param resp: MercuryClient.Response
        """
        if resp.uri == "spotify:user:attributes:update":
            attributes_update = UserAttributesUpdate()
            attributes_update.ParseFromString(resp.payload)
            for pair in attributes_update.pairs_list:
                self.__user_attributes[pair.key] = pair.value
                self.logger.info("Updated user attribute: {} -> {}".format(
                    pair.key, pair.value))
    
    def get_user_attribute(self, key, fallback=None):
        """
        :param key: str
        :param fallback: str (Default value = None)
        """
        return (self.__user_attributes.get(key)
                if self.__user_attributes.get(key) is not None else fallback)
        
    def is_valid(self):
        """ """
        if self.__closed:
            return False
        self.__wait_auth_lock()
        return self.__ap_welcome is not None and self.connection is not None
    
    def mercury(self):
        """ """
        self.__wait_auth_lock()
        if self.__mercury_client is None:
            raise RuntimeError("Session isn't authenticated!")
        return self.__mercury_client
    
    def on_message(self, uri, headers, payload):
        """
        :param uri: str
        :param headers: dict
        :param payload: bytes
        """
        if uri == "hm://connect-state/v1/connect/logout":
            self.close()
            
    def parse_product_info(self, data):
        """Parse product information

        :param data: Raw product information
        """
        products = defusedxml.ElementTree.fromstring(data)
        if products is None:
            return
        product = products[0]
        if product is None:
            return
        for i in range(len(product)):
            self.__user_attributes[product[i].tag] = product[i].text
        self.logger.debug("Parsed product info: {}".format(
            self.__user_attributes))
        
    def preferred_locale(self):
        """ """
        return self.__inner.preferred_locale
    
    def reconnect(self):
        """Reconnect to the Spotify Server"""
        if self.connection is not None:
            self.connection.close()
            self.__receiver.stop()
        self.connection = Session.ConnectionHolder.create(
            ApResolver.get_random_accesspoint(), self.__inner.conf)
        self.connect()
        self.__authenticate_partial(
            Authentication.LoginCredentials(
                typ=self.__ap_welcome.reusable_auth_credentials_type,
                username=self.__ap_welcome.canonical_username,
                auth_data=self.__ap_welcome.reusable_auth_credentials,
            ),
            True,
        )
        self.logger.info("Re-authenticated as {}!".format(
            self.__ap_welcome.canonical_username))
        
    def reconnecting(self):
        """ """
        return not self.__closing and not self.__closed and self.connection is None
    
    def search(self):
        """ """
        self.__wait_auth_lock()
        if self.__search is None:
            raise RuntimeError("Session isn't authenticated!")
        return self.__search
    
    def send(self, cmd, payload):
        """Send data to socket using send_unchecked

        :param cmd: Command
        :param payload: Payload
        """
        if self.__closing and self.connection is None:
            self.logger.debug("Connection was broken while closing.")
            return
        if self.__closed:
            raise RuntimeError("Session is closed!")
        with self.__auth_lock:
            if self.cipher_pair is None or self.__auth_lock_bool:
                self.__auth_lock.wait()
            self.__send_unchecked(cmd, payload)
    
    def tokens(self):
        """ """
        self.__wait_auth_lock()
        if self.__token_provider is None:
            raise RuntimeError("Session isn't authenticated!")
        return self.__token_provider
    
    def username(self):
        """ """
        return self.__ap_welcome.canonical_username
    
    def stored(self):
        """ """
        return self.__stored_str
    
    def __authenticate_partial(self, credential, remove_lock):
        """
        Login to Spotify
        Args:
            credential: Spotify account login information
        """
        if self.cipher_pair is None:
            raise RuntimeError("Connection not established!")
        client_response_encrypted_proto = Authentication.ClientResponseEncrypted(
            login_credentials=credential,
            system_info=Authentication.SystemInfo(
                os=0,
                cpu_family=0,
                system_information_string=Version.system_info_string(),
                device_id=self.__inner.device_id,
            ),
            version_string=Version.version_string(),
        )
        self.__send_unchecked(
            Packet.Type.login,
            client_response_encrypted_proto.SerializeToString())
        packet = self.cipher_pair.receive_encoded(self.connection)
        if packet.is_cmd(Packet.Type.ap_welcome):
            self.__ap_welcome = Authentication.APWelcome()
            self.__ap_welcome.ParseFromString(packet.payload)
            self.__receiver = Session.Receiver(self)
            bytes0x0f = get_random_bytes(0x14)
            self.__send_unchecked(Packet.Type.unknown_0x0f, bytes0x0f)
            preferred_locale = io.BytesIO()
            preferred_locale.write(b"\x00\x00\x10\x00\x02preferred-locale" +
                                self.__inner.preferred_locale.encode())
            preferred_locale.seek(0)
            self.__send_unchecked(Packet.Type.preferred_locale,
                                preferred_locale.read())
            if remove_lock:
                with self.__auth_lock:
                    self.__auth_lock_bool = False
                    self.__auth_lock.notify_all()
            if self.__inner.conf.store_credentials:
                reusable = self.__ap_welcome.reusable_auth_credentials
                reusable_type = Authentication.AuthenticationType.Name(
                    self.__ap_welcome.reusable_auth_credentials_type)
                if self.__inner.conf.stored_credentials_file is None:
                    raise TypeError(
                        "The file path to be saved is not specified")
                self.__stored_str = base64.b64encode(
                    json.dumps({
                        "username":
                        self.__ap_welcome.canonical_username,
                        "credentials":
                        base64.b64encode(reusable).decode(),
                        "type":
                        reusable_type,
                    }).encode()).decode()
                with open(self.__inner.conf.stored_credentials_file, "w") as f:
                    json.dump(
                        {
                            "username": self.__ap_welcome.canonical_username,
                            "credentials": base64.b64encode(reusable).decode(),
                            "type": reusable_type,
                        },
                        f,
                    )

        elif packet.is_cmd(Packet.Type.auth_failure):
            ap_login_failed = Keyexchange.APLoginFailed()
            ap_login_failed.ParseFromString(packet.payload)
            self.close()
            raise Session.SpotifyAuthenticationException(ap_login_failed)
        else:
            raise RuntimeError("Unknown CMD 0x" + packet.cmd.hex())
        
    def __send_unchecked(self, cmd, payload):
        self.cipher_pair.send_encoded(self.connection, cmd, payload)
        
    def __wait_auth_lock(self):
        if self.__closing and self.connection is None:
            self.logger.debug("Connection was broken while closing.")
            return
        if self.__closed:
            raise RuntimeError("Session is closed!")
        with self.__auth_lock:
            if self.cipher_pair is None or self.__auth_lock_bool:
                self.__auth_lock.wait()
                    
    class AbsBuilder:
        """ """
        conf = None
        device_id = None
        device_name = "librespot-python"
        device_type = Connect.DeviceType.COMPUTER
        preferred_locale = "en"

        def __init__(self, conf=None):
            if conf is None:
                self.conf = Session.Configuration.Builder().build()
            else:
                self.conf = conf

        def set_preferred_locale(self, locale):
            """
            :param locale: str:
            """
            if len(locale) != 2:
                raise TypeError("Invalid locale: {}".format(locale))
            self.preferred_locale = locale
            return self

        def set_device_name(self, device_name):
            """
            :param device_name: str:
            """
            self.device_name = device_name
            return self

        def set_device_id(self, device_id):
            """
            :param device_id: str:
            """
            if self.device_id is not None and len(device_id) != 40:
                raise TypeError("Device ID must be 40 chars long.")
            self.device_id = device_id
            return self

        def set_device_type(self, device_type):
            """
            :param device_type: Connect.DeviceType:
            """
            self.device_type = device_type
            return self   
        
    class Accumulator:
        """ """
        # Removed type annotation for Python 2.7 compatibility
        # __buffer: io.BytesIO

        def __init__(self):
            self.__buffer = io.BytesIO()

        def read(self):
            """Read all buffer

            :returns: All buffer
            """
            pos = self.__buffer.tell()
            self.__buffer.seek(0)
            data = self.__buffer.read()
            self.__buffer.seek(pos)
            return data

        def write(self, data):
            """Write data to buffer

            :param data: Bytes to be written
            """
            self.__buffer.write(data)

        def write_int(self, data):
            """Write data to buffer

            :param data: Integer to be written
            """
            self.write(struct.pack(">i", data))

        def write_short(self, data):
            """Write data to buffer

            :param data: Short integer to be written
            """
            self.write(struct.pack(">h", data))

    class Builder(AbsBuilder):
        login_credentials = None

        def blob(self, username, blob):
            if self.device_id is None:
                raise TypeError("You must specify the device ID first.")
            self.login_credentials = self.decrypt_blob(self.device_id, username, blob)
            return self

        def decrypt_blob(self, device_id, username, encrypted_blob):
            encrypted_blob = base64.b64decode(encrypted_blob)
            sha1 = SHA1.new()
            sha1.update(device_id.encode())
            secret = sha1.digest()
            base_key = PBKDF2(secret, username.encode(), 20, 0x100, hmac_hash_module=SHA1)
            sha1 = SHA1.new()
            sha1.update(base_key)
            key = sha1.digest() + b"\x00\x00\x00\x14"
            aes = AES.new(key, AES.MODE_ECB)
            decrypted_blob = bytearray(aes.decrypt(encrypted_blob))
            l = len(decrypted_blob)
            for i in range(0, l - 0x10):
                decrypted_blob[l - i - 1] ^= decrypted_blob[l - i - 0x11]
            blob = io.BytesIO(decrypted_blob)
            blob.read(1)
            le = self.read_blob_int(blob)
            blob.read(le)
            blob.read(1)
            type_int = self.read_blob_int(blob)
            type_ = Authentication.AuthenticationType.Name(type_int)
            if type_ is None:
                raise IOError(TypeError("Unknown AuthenticationType: {}".format(type_int)))
            blob.read(1)
            l = self.read_blob_int(blob)
            auth_data = blob.read(l)
            return Authentication.LoginCredentials(auth_data=auth_data, typ=type_, username=username)

        def read_blob_int(self, buffer):
            lo = buffer.read(1)
            if (ord(lo) & 0x80) == 0:
                return ord(lo)
            hi = buffer.read(1)
            return ord(lo) & 0x7F | ord(hi) << 7

        def stored(self, stored_credentials_str):
            try:
                obj = json.loads(base64.b64decode(stored_credentials_str))
            except (binascii.Error, ValueError):
                pass
            else:
                try:
                    self.login_credentials = Authentication.LoginCredentials(
                        typ=Authentication.AuthenticationType.Value(obj["type"]),
                        username=obj["username"],
                        auth_data=base64.b64decode(obj["credentials"]),
                    )
                except KeyError:
                    pass
            return self

        def stored_file(self, stored_credentials=None):
            if stored_credentials is None:
                stored_credentials = self.conf.stored_credentials_file
            if os.path.isfile(stored_credentials):
                try:
                    with open(stored_credentials) as f:
                        obj = json.load(f)
                except ValueError:
                    pass
                else:
                    try:
                        self.login_credentials = Authentication.LoginCredentials(
                            typ=Authentication.AuthenticationType.Value(obj["type"]),
                            username=obj["username"],
                            auth_data=base64.b64decode(obj["credentials"]),
                        )
                    except KeyError:
                        pass
            return self

        def user_pass(self, username, password):
            self.login_credentials = Authentication.LoginCredentials(
                username=username,
                typ=0,
                auth_data=password.encode(),
            )
            return self

        def create(self):
            if self.login_credentials is None:
                raise RuntimeError("You must select an authentication method.")
            session = Session(
                Session.Inner(
                    self.device_type,
                    self.device_name,
                    self.preferred_locale,
                    self.conf,
                    self.device_id,
                ),
                ApResolver.get_random_accesspoint(),
            )
            session.connect()
            session.authenticate(self.login_credentials)
            return session

    class Configuration:
        """ """
        # Proxy
        # proxyEnabled = None
        # proxyType = None
        # proxyAddress = None
        # proxyPort = None
        # proxyAuth = None
        # proxyUsername = None
        # proxyPassword = None

        # Cache
        cache_enabled = None
        cache_dir = None
        do_cache_clean_up = None

        # Stored credentials
        store_credentials = None
        stored_credentials_file = None

        # Fetching
        retry_on_chunk_error = None

        def __init__(
            self,
            # proxy_enabled,
            # proxy_type,
            # proxy_address,
            # proxy_port,
            # proxy_auth,
            # proxy_username,
            # proxy_password,
            cache_enabled,
            cache_dir,
            do_cache_clean_up,
            store_credentials,
            stored_credentials_file,
            retry_on_chunk_error,
        ):
            # self.proxyEnabled = proxy_enabled
            # self.proxyType = proxy_type
            # self.proxyAddress = proxy_address
            # self.proxyPort = proxy_port
            # self.proxyAuth = proxy_auth
            # self.proxyUsername = proxy_username
            # self.proxyPassword = proxy_password
            self.cache_enabled = cache_enabled
            self.cache_dir = cache_dir
            self.do_cache_clean_up = do_cache_clean_up
            self.store_credentials = store_credentials
            self.stored_credentials_file = stored_credentials_file
            self.retry_on_chunk_error = retry_on_chunk_error

        class Builder:
            """ """
            # Proxy
            # proxyEnabled = False
            # proxyType = Proxy.Type.DIRECT
            # proxyAddress = None
            # proxyPort = None
            # proxyAuth = None
            # proxyUsername = None
            # proxyPassword = None

            # Cache
            cache_enabled = True
            cache_dir = os.path.join(os.getcwd(), "cache")
            do_cache_clean_up = True

            # Stored credentials
            store_credentials = True
            stored_credentials_file = os.path.join(os.getcwd(), "credentials.json")

            # Fetching
            retry_on_chunk_error = True

            # def set_proxy_enabled(self, proxy_enabled):
            #     self.proxyEnabled = proxy_enabled
            #     return self

            # def set_proxy_type(self, proxy_type):
            #     self.proxyType = proxy_type
            #     return self

            # def set_proxy_address(self, proxy_address):
            #     self.proxyAddress = proxy_address
            #     return self

            # def set_proxy_auth(self, proxy_auth):
            #     self.proxyAuth = proxy_auth
            #     return self

            # def set_proxy_username(self, proxy_username):
            #     self.proxyUsername = proxy_username
            #     return self

            # def set_proxy_password(self, proxy_password):
            #     self.proxyPassword = proxy_password
            #     return self

            def set_cache_enabled(self, cache_enabled):
                """Set cache_enabled

                :param cache_enabled: bool
                :returns: Builder
                """
                self.cache_enabled = cache_enabled
                return self

            def set_cache_dir(self, cache_dir):
                """Set cache_dir

                :param cache_dir: str
                :returns: Builder
                """
                self.cache_dir = cache_dir
                return self

            def set_do_cache_clean_up(self, do_cache_clean_up):
                """Set do_cache_clean_up

                :param do_cache_clean_up: bool
                :returns: Builder
                """
                self.do_cache_clean_up = do_cache_clean_up
                return self

            def set_store_credentials(self, store_credentials):
                """Set store_credentials

                :param store_credentials: bool
                :returns: Builder
                """
                self.store_credentials = store_credentials
                return self

            def set_stored_credential_file(self, stored_credential_file):
                """Set stored_credential_file

                :param stored_credential_file: str
                :returns: Builder
                """
                self.stored_credentials_file = stored_credential_file
                return self

            def set_retry_on_chunk_error(self, retry_on_chunk_error):
                """Set retry_on_chunk_error

                :param retry_on_chunk_error: bool
                :returns: Builder
                """
                self.retry_on_chunk_error = retry_on_chunk_error
                return self

            def build(self):
                """Build Configuration instance

                :returns: Configuration
                """
                return Session.Configuration(
                    # self.proxyEnabled,
                    # self.proxyType,
                    # self.proxyAddress,
                    # self.proxyPort,
                    # self.proxyAuth,
                    # self.proxyUsername,
                    # self.proxyPassword,
                    self.cache_enabled,
                    self.cache_dir,
                    self.do_cache_clean_up,
                    self.store_credentials,
                    self.stored_credentials_file,
                    self.retry_on_chunk_error,
                )

    class ConnectionHolder:
        """ """
        def __init__(self, sock):
            self.__buffer = io.BytesIO()
            self.__socket = sock

        @staticmethod
        def create(address, conf):
            """Create the ConnectionHolder instance

            :param address: Address to connect
            :param address: str:
            :param conf:
            :returns: ConnectionHolder instance

            """
            ap_address = address.split(":")[0]
            ap_port = int(address.split(":")[1])
            sock = socket.socket()
            sock.connect((ap_address, ap_port))
            return Session.ConnectionHolder(sock)

        def close(self):
            """Close the connection"""
            self.__socket.close()

        def flush(self):
            """Flush data to socket"""
            try:
                self.__buffer.seek(0)
                self.__socket.send(self.__buffer.read())
                self.__buffer = io.BytesIO()
            except socket.error:
                pass

        def read(self, length):
            """Read data from socket

            :param length: int:
            :returns: Bytes data from socket

            """
            return self.__socket.recv(length)

        def read_int(self):
            """Read integer from socket

            :returns: integer from socket

            """
            return struct.unpack(">i", self.read(4))[0]

        def read_short(self):
            """Read short integer from socket

            :returns: short integer from socket

            """
            return struct.unpack(">h", self.read(2))[0]

        def set_timeout(self, seconds):
            """Set socket's timeout

            :param seconds: Number of seconds until timeout
            :param seconds: float:

            """
            self.__socket.settimeout(None if seconds == 0 else seconds)

        def write(self, data):
            """Write data to buffer

            :param data: Bytes to be written
            :param data: bytes:

            """
            self.__buffer.write(data)

        def write_int(self, data):
            """Write data to buffer

            :param data: Integer to be written
            :param data: int:

            """
            self.write(struct.pack(">i", data))

        def write_short(self, data):
            """Write data to buffer

            :param data: Short integer to be written
            :param data: int:

            """
            self.write(struct.pack(">h", data))      
            
    class Inner:
        """ """
        def __init__(
            self,
            device_type,
            device_name,
            preferred_locale,
            conf,
            device_id=None,
        ):
            self.preferred_locale = preferred_locale
            self.conf = conf
            self.device_type = device_type
            self.device_name = device_name
            self.device_id = device_id if device_id is not None else util.random_hex_string(40)

    class Receiver:
        """ """
        def __init__(self, session):
            self.__session = session
            self.__thread = threading.Thread(target=self.run)
            self.__thread.daemon = True
            self.__thread.name = "session-packet-receiver"
            self.__running = True
            self.__thread.start()

        def stop(self):
            """ """
            self.__running = False

        def run(self):
            """Receive Packet thread function"""
            self.__session.logger.info("Session.Receiver started")
            while self.__running:
                try:
                    packet = self.__session.cipher_pair.receive_encoded(self.__session.connection)
                    cmd = Packet.Type.parse(packet.cmd)
                    if cmd is None:
                        self.__session.logger.info(
                            "Skipping unknown command cmd: 0x{}, payload: {}".format(
                                util.bytes_to_hex(packet.cmd), packet.payload))
                        continue
                except (RuntimeError, socket.error) as ex:
                    if self.__running:
                        self.__session.logger.fatal("Failed reading packet! {}".format(ex))
                        self.__session.reconnect()
                    break
                if not self.__running:
                    break
                if cmd == Packet.Type.ping:
                    if self.__session.scheduled_reconnect is not None:
                        self.__session.scheduler.cancel(self.__session.scheduled_reconnect)

                    def anonymous():
                        """ """
                        self.__session.logger.warning("Socket timed out. Reconnecting...")
                        self.__session.reconnect()

                    self.__session.scheduled_reconnect = self.__session.scheduler.enter(
                        2 * 60 + 5, 1, anonymous)
                    self.__session.send(Packet.Type.pong, packet.payload)
                elif cmd == Packet.Type.pong_ack:
                    continue
                elif cmd == Packet.Type.country_code:
                    self.__session.__country_code = packet.payload.decode()
                    self.__session.logger.info(
                        "Received country_code: {}".format(self.__session.__country_code))
                elif cmd == Packet.Type.license_version:
                    license_version = io.BytesIO(packet.payload)
                    license_id = struct.unpack(">h", license_version.read(2))[0]
                    if license_id != 0:
                        buffer = license_version.read()
                        self.__session.logger.info(
                            "Received license_version: {}, {}".format(license_id, buffer.decode()))
                    else:
                        self.__session.logger.info("Received license_version: {}".format(license_id))
                elif cmd == Packet.Type.unknown_0x10:
                    self.__session.logger.debug("Received 0x10: {}".format(util.bytes_to_hex(packet.payload)))
                elif cmd in [
                    Packet.Type.mercury_sub,
                    Packet.Type.mercury_unsub,
                    Packet.Type.mercury_event,
                    Packet.Type.mercury_req,
                ]:
                    self.__session.mercury().dispatch(packet)
                elif cmd in [Packet.Type.aes_key, Packet.Type.aes_key_error]:
                    self.__session.audio_key().dispatch(packet)
                elif cmd in [Packet.Type.channel_error, Packet.Type.stream_chunk_res]:
                    self.__session.channel().dispatch(packet)
                elif cmd == Packet.Type.product_info:
                    self.__session.parse_product_info(packet.payload)
                else:
                    self.__session.logger.info("Skipping {}".format(util.bytes_to_hex(cmd)))
                    
    class SpotifyAuthenticationException(Exception):
        """ """
        def __init__(self, login_failed):
            super().__init__(Keyexchange.ErrorCode.Name(login_failed.error_code))

class SearchManager:
    """ """
    base_url = "hm://searchview/km/v4/search/"
    
    def __init__(self, session):
        self.__session = session

    def request(self, request):
        """
        :param request: SearchRequest:
        """
        if request.get_username() == "":
            request.set_username(self.__session.username())
        if request.get_country() == "":
            request.set_country(self.__session.country_code)
        if request.get_locale() == "":
            request.set_locale(self.__session.preferred_locale())
        response = self.__session.mercury().send_sync(
            RawMercuryRequest.new_builder().set_method("GET").set_uri(
                request.build_url()).build())
        if response.status_code != 200:
            raise SearchManager.SearchException(response.status_code)
        return json.loads(response.payload)

    class SearchException(Exception):
        """ """
        def __init__(self, status_code):
            super(SearchManager.SearchException, self).__init__(
                "Search failed with code {}.".format(status_code))

    class SearchRequest:
        """ """
        __catalogue = ""
        __country = ""
        __image_size = ""
        __limit = 10
        __locale = ""
        __username = ""

        def __init__(self, query):
            self.query = query
            if query == "":
                raise TypeError

        def build_url(self):
            """ """
            url = SearchManager.base_url + urllib.quote(self.query)
            url += "?entityVersion=2"
            url += "&catalogue=" + urllib.quote(self.__catalogue)
            url += "&country=" + urllib.quote(self.__country)
            url += "&imageSize=" + urllib.quote(self.__image_size)
            url += "&limit=" + str(self.__limit)
            url += "&locale=" + urllib.quote(self.__locale)
            url += "&username=" + urllib.quote(self.__username)
            return url

        def get_catalogue(self):
            """ """
            return self.__catalogue

        def get_country(self):
            """ """
            return self.__country

        def get_image_size(self):
            """ """
            return self.__image_size

        def get_limit(self):
            """ """
            return self.__limit

        def get_locale(self):
            """ """
            return self.__locale

        def get_username(self):
            """ """
            return self.__username

        def set_catalogue(self, catalogue):
            """
            :param catalogue: str:
            """
            self.__catalogue = catalogue
            return self

        def set_country(self, country):
            """
            :param country: str:
            """
            self.__country = country
            return self

        def set_image_size(self, image_size):
            """
            :param image_size: str:
            """
            self.__image_size = image_size
            return self

        def set_limit(self, limit):
            """
            :param limit: int:
            """
            self.__limit = limit
            return self

        def set_locale(self, locale):
            """
            :param locale: str:
            """
            self.__locale = locale
            return self

        def set_username(self, username):
            """
            :param username: str:
            """
            self.__username = username
            return self
            
class TokenProvider:
    """ """
    logger = logging.getLogger("Librespot:TokenProvider")
    token_expire_threshold = 10
    __tokens = []

    def __init__(self, session):
        self._session = session

    def find_token_with_all_scopes(self, scopes):
        """
        :param scopes: list of str
        """
        for token in self.__tokens:
            if token.has_scopes(scopes):
                return token
        return None

    def get(self, scope):
        """
        :param scope: str
        """
        return self.get_token(scope).access_token

    def get_token(self, *scopes):
        """
        :param *scopes: list of str
        """
        scopes = list(scopes)
        if len(scopes) == 0:
            raise RuntimeError("The token doesn't have any scope")
        token = self.find_token_with_all_scopes(scopes)
        if token is not None:
            if token.expired():
                self.__tokens.remove(token)
            else:
                return token
        self.logger.debug(
            "Token expired or not suitable, requesting again. scopes: {}, old_token: {}"
            .format(scopes, token))
        response = self._session.mercury().send_sync_json(
            MercuryRequests.request_token(self._session.device_id(),
                                          ",".join(scopes)))
        token = TokenProvider.StoredToken(response)
        self.logger.debug(
            "Updated token successfully! scopes: {}, new_token: {}".format(
                scopes, token))
        self.__tokens.append(token)
        return token

    class StoredToken:
        """ """
        def __init__(self, obj):
            self.timestamp = int(time.time() * 1000)
            self.expires_in = obj["expiresIn"]
            self.access_token = obj["accessToken"]
            self.scopes = obj["scope"]

        def expired(self):
            """ """
            return self.timestamp + (self.expires_in - TokenProvider.token_expire_threshold) * 1000 < int(time.time() * 1000)

        def has_scope(self, scope):
            """
            :param scope: str
            """
            for s in self.scopes:
                if s == scope:
                    return True
            return False

        def has_scopes(self, sc):
            """
            :param sc: list of str
            """
            for s in sc:
                if not self.has_scope(s):
                    return False
            return True

class Version:
    version_name = "1.0.0"

    @staticmethod
    def platform():
        return Platform.PLATFORM_OSX_X86

    @staticmethod
    def version_number():
        return Version.version_name

    @staticmethod
    def version_string():
        return "librespot-python " + Version.version_name

    @staticmethod
    def system_info_string():
        return Version.version_string() + "; Python " + platform.python_version() + "; " + platform.system()
    
    @staticmethod
    def standard_build_info():
        build_info = BuildInfo()
        build_info.product = Product.PRODUCT_CLIENT
        build_info.product_flags.append(ProductFlags.PRODUCT_FLAG_NONE)
        build_info.platform = Version.platform()
        build_info.version = 117300517
        return build_info
        
class DiffieHellman:
    """
    Diffie-Hellman Key Exchange
    """
    __prime = int(
        "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B302B0A6DF2524C978CC709B9FEA130203DADD62A32FF"
        "FFFFFFFFFFFFFFFF", 16)
    __generator = 2

    def __init__(self):
        key_data = Random.get_random_bytes(0x5f)
        self.__private_key = int(key_data.encode('hex'), 16)
        self.__public_key = pow(self.__generator, self.__private_key, self.__prime)

    def compute_shared_key(self, remote_key_bytes):
        """
        Compute shared_key
        """
        remote_key = int(remote_key_bytes.encode('hex'), 16)
        return pow(remote_key, self.__private_key, self.__prime)

    def private_key(self):
        """
        Return DiffieHellman's private key
        Returns:
            DiffieHellman's private key
        """
        return self.__private_key

    def public_key(self):
        """
        Return DiffieHellman's public key
        Returns:
            DiffieHellman's public key
        """
        return self.__public_key

    def public_key_bytes(self):
        """
        Return DiffieHellman's packed public key
        Returns:
            DiffieHellman's packed public key
        """
        return util.int_to_bytes(self.__public_key)
    
def test_ap_resolver():
    try:
        dealer_url = ApResolver.get_random_dealer()
        print("Dealer URL:", dealer_url)
    except Exception as e:
        print("Error getting dealer URL:", e)

    try:
        spclient_url = ApResolver.get_random_spclient()
        print("Spclient URL:", spclient_url)
    except Exception as e:
        print("Error getting spclient URL:", e)

    try:
        accesspoint_url = ApResolver.get_random_accesspoint()
        print("Accesspoint URL:", accesspoint_url)
    except Exception as e:
        print("Error getting accesspoint URL:", e)

def login():
    global session

    while True:
        user_name = raw_input("UserName: ")
        password = raw_input("Password: ")
        try:
            session = Session.Builder().user_pass(user_name, password).create()
            return
        except RuntimeError:
            pass

# def get_spotify_endpoint():
#     apresolve_url = 'http://apresolve.spotify.com/?type=accesspoint'
#     response = requests.get(apresolve_url)
#     if response.status_code == 200:
#         access_points = response.json().get('accesspoint', [])
#         return access_points[0]
#     else:
#         raise Exception("Failed to fetch Spotify endpoint: {}".format(response.status_code))

# def connect_to_spotify(endpoint):
#     addr, port = endpoint.split(':')
#     port = int(port)
    
#     sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#     sock.connect((addr, port))
#     print("Connected to {}:{}".format(addr, port))
    
#     try:
#         client_hello, dh = create_client_hello()
#         print("this is the client_hello-->{}".format(client_hello))
#         client_hello_bytes = client_hello.SerializeToString()
        
#         acc = Accumulator()
#         acc.write(b"\x00\x04")
#         acc.write_int(2 + 4 + len(client_hello_bytes))
#         acc.write(client_hello_bytes)
        
#         sock.sendall(acc.read())
#         print("Sent ClientHello to server")
        
#         # Read the APResponseMessage length
#         try: 
#             response_length_data = sock.recv(4)
#             if not response_length_data:
#                 raise Exception("No response from server")
            
#             response_length = struct.unpack('>I', response_length_data)[0]
#             print("Received response length:", response_length)

#             response_data = sock.recv(response_length)
#             if not response_data:
#                 raise Exception("No response data received")
            
#             print("Received response:", response_data)
            
#             print("Server response:", response_data)
        
#         except Exception as e:
#             print("Error receiving response: ", e)
    
#     finally:
#         sock.close()

# def create_client_hello():
#     dh = DiffieHellman()
#     dh_public_key = dh.public_key_bytes()
    
#     nonce = get_random_bytes(16)
#     padding = b'\x1e'
    
#     client_hello = ClientHello()
#     client_hello.build_info.CopyFrom(Version.standard_build_info())
#     client_hello.cryptosuites_supported.append(_CRYPTOSUITE.values_by_name['CRYPTO_SUITE_SHANNON'].number)
    
#     login_crypto_hello_union = LoginCryptoHelloUnion()
#     dh_hello = LoginCryptoDiffieHellmanHello(gc=dh_public_key, server_keys_known=1)
#     login_crypto_hello_union.diffie_hellman.CopyFrom(dh_hello)
    
#     client_hello.login_crypto_hello.CopyFrom(login_crypto_hello_union)
#     client_hello.client_nonce = nonce
#     client_hello.padding = padding
    
#     return client_hello, dh

# def handle_server_response(sock):
#     try:
#         # Read the length of the response (4 bytes)
#         print("i'm trying 1")
#         response_length_data = sock.recv(4)
#         response_length = struct.unpack('>I', response_length_data)[0]  # Unpack 4 bytes as unsigned integer
#         print("Received response length:", response_length)

#         acc = Accumulator()
#         acc.write(response_length_data)

#         # Read the rest of the response based on response_length
#         buffer_size = response_length - 4  # Adjust for the initial 4 bytes read

#         while len(acc.buffer) < response_length:
#             chunk = sock.recv(min(buffer_size - len(acc.buffer), 4096))
#             if not chunk:  # Handle potential broken connection
#                 raise RuntimeError("Socket connection broken")
            
#             acc.write(chunk)
#             received_so_far = len(acc.buffer)
#             print("Received %d bytes. Total received: %d / %d" % (len(chunk), received_so_far, response_length))

#         print("Finished receiving data.")
#         print("Total bytes received:", len(acc.buffer))

#         # Parse APResponseMessage
#         response_data = acc.to_bytes()[4:]  # Skip the initial 4 bytes if they are metadata
#         ap_response_message = APResponseMessage()
#         ap_response_message.ParseFromString(response_data)

#         print("Parsed APResponseMessage:")
#         print(ap_response_message)

#         # Example of further processing:
#         # Extract necessary information from ap_response_message and proceed accordingly

#     except socket.timeout as e:
#         print("Socket timeout:", e)
#     except struct.error as e:
#         print("Error unpacking response length data:", e)
#     except IOError as e:
#         print("I/O error:", e)
#     except RuntimeError as e:
#         print("Runtime error:", e)
#     except Exception as e:
#         print("Error handling server response:", e)
#     finally:
#         sock.close()


def main():
    login()
    # try:
    #     endpoint = get_spotify_endpoint()
    #     print("Spotify endpoint: {}".format(endpoint))
        
    #     connect_to_spotify(endpoint)
        
    # except Exception as e:
    #     print("Error: {}".format(e))

if __name__ == "__main__":
    main()

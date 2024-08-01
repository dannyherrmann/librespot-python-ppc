import util
from context_track_pb2 import ContextTrack
from util import Base62
import re

class SpotifyId:
    STATIC_FROM_URI = "fromUri"
    STATIC_FROM_BASE62 = "fromBase62"
    STATIC_FROM_HEX = "fromHex"

    @staticmethod
    def from_base62(base62):
        raise NotImplementedError

    @staticmethod
    def from_hex(hex_str):
        raise NotImplementedError

    @staticmethod
    def from_uri(uri):
        raise NotImplementedError

    def to_spotify_uri(self):
        raise NotImplementedError

    class SpotifyIdParsingException(Exception):
        pass
    
class PlayableId:
    base62 = Base62.create_instance_with_inverted_character_set()

    @staticmethod
    def from_uri(uri):
        if not PlayableId.is_supported(uri):
            return UnsupportedId(uri)
        if TrackId.pattern.search(uri) is not None:
            return TrackId.from_uri(uri)
        if EpisodeId.pattern.search(uri) is not None:
            return EpisodeId.from_uri(uri)
        raise TypeError("Unknown uri: %s" % uri)

    @staticmethod
    def is_supported(uri):
        return (not uri.startswith("spotify:local:")
                and not uri == "spotify:delimiter"
                and not uri == "spotify:meta:delimiter")

    @staticmethod
    def should_play(track):
        return track.metadata_or_default

    def get_gid(self):
        raise NotImplementedError

    def hex_id(self):
        raise NotImplementedError

    def to_spotify_uri(self):
        raise NotImplementedError
    
class PlaylistId(SpotifyId):
    base62 = Base62.create_instance_with_inverted_character_set()
    pattern = re.compile(r"spotify:playlist:(.{22})")
    __id = None

    def __init__(self, _id):
        self.__id = _id

    @staticmethod
    def from_uri(uri):
        matcher = PlaylistId.pattern.search(uri)
        if matcher is not None:
            playlist_id = matcher.group(1)
            return PlaylistId(playlist_id)
        raise TypeError("Not a Spotify playlist ID: {}.".format(uri))

    def id(self):
        return self.__id

    def to_spotify_uri(self):
        return "spotify:playlist:" + self.__id
    
class UnsupportedId(PlayableId):
    def __init__(self, uri):
        self.uri = uri

    def get_gid(self):
        raise TypeError()

    def hex_id(self):
        raise TypeError()

    def to_spotify_uri(self):
        return self.uri
    
class AlbumId(SpotifyId):
    base62 = Base62.create_instance_with_inverted_character_set()
    pattern = re.compile(r"spotify:album:(.{22})")

    def __init__(self, hex_id):
        self.__hex_id = hex_id.lower()

    @staticmethod
    def from_uri(uri):
        matcher = AlbumId.pattern.search(uri)
        if matcher is not None:
            album_id = matcher.group(1)
            return AlbumId(util.bytes_to_hex(AlbumId.base62.decode(album_id.encode(), 16)))
        raise TypeError("Not a Spotify album ID: %s." % uri)

    @staticmethod
    def from_base62(base62):
        return AlbumId(util.bytes_to_hex(AlbumId.base62.decode(base62.encode(), 16)))

    @staticmethod
    def from_hex(hex_str):
        return AlbumId(hex_str)

    def to_mercury_uri(self):
        return "hm://metadata/4/album/%s" % self.__hex_id

    def hex_id(self):
        return self.__hex_id

    def to_spotify_uri(self):
        return "spotify:album:%s" % AlbumId.base62.encode(util.hex_to_bytes(self.__hex_id)).decode()
    
class ArtistId(SpotifyId):
    base62 = Base62.create_instance_with_inverted_character_set()
    pattern = re.compile("spotify:artist:(.{22})")

    def __init__(self, hex_id):
        self.__hex_id = hex_id.lower()

    @staticmethod
    def from_uri(uri):
        matcher = ArtistId.pattern.search(uri)
        if matcher is not None:
            artist_id = matcher.group(1)
            return ArtistId(
                util.bytes_to_hex(ArtistId.base62.decode(artist_id.encode(), 16)))
        raise TypeError("Not a Spotify artist ID: %s" % uri)

    @staticmethod
    def from_base62(base62):
        return ArtistId(util.bytes_to_hex(ArtistId.base62.decode(base62.encode(), 16)))

    @staticmethod
    def from_hex(hex_str):
        return ArtistId(hex_str)

    def to_mercury_uri(self):
        return "hm://metadata/4/artist/%s" % self.__hex_id

    def to_spotify_uri(self):
        return "spotify:artist:%s" % ArtistId.base62.encode(util.hex_to_bytes(self.__hex_id)).decode()

    def hex_id(self):
        return self.__hex_id
    
class EpisodeId(SpotifyId, PlayableId):
    pattern = re.compile(r"spotify:episode:(.{22})")

    def __init__(self, hex_id):
        self.__hex_id = hex_id.lower()

    @staticmethod
    def from_uri(uri):
        matcher = EpisodeId.pattern.search(uri)
        if matcher is not None:
            episode_id = matcher.group(1)
            return EpisodeId(
                util.bytes_to_hex(PlayableId.base62.decode(episode_id.encode(), 16)))
        raise TypeError("Not a Spotify episode ID: %s" % uri)

    @staticmethod
    def from_base62(base62):
        return EpisodeId(
            util.bytes_to_hex(PlayableId.base62.decode(base62.encode(), 16)))

    @staticmethod
    def from_hex(hex_str):
        return EpisodeId(hex_str)

    def to_mercury_uri(self):
        return "hm://metadata/4/episode/%s" % self.__hex_id

    def to_spotify_uri(self):
        return "Spotify:episode:%s" % PlayableId.base62.encode(util.hex_to_bytes(self.__hex_id)).decode()

    def hex_id(self):
        return self.__hex_id

    def get_gid(self):
        return util.hex_to_bytes(self.__hex_id)
    
class ShowId(SpotifyId):
    base62 = Base62.create_instance_with_inverted_character_set()
    pattern = re.compile("spotify:show:(.{22})")

    def __init__(self, hex_id):
        self.__hex_id = hex_id

    @staticmethod
    def from_uri(uri):
        matcher = ShowId.pattern.search(uri)
        if matcher is not None:
            show_id = matcher.group(1)
            return ShowId(util.bytes_to_hex(ShowId.base62.decode(show_id.encode(), 16)))
        raise TypeError("Not a Spotify show ID: %s" % uri)

    @staticmethod
    def from_base62(base62):
        return ShowId(util.bytes_to_hex(ShowId.base62.decode(base62.encode(), 16)))

    @staticmethod
    def from_hex(hex_str):
        return ShowId(hex_str)

    def to_mercury_uri(self):
        return "hm://metadata/4/show/%s" % self.__hex_id

    def to_spotify_uri(self):
        return "spotify:show:%s" % ShowId.base62.encode(util.hex_to_bytes(self.__hex_id)).decode()

    def hex_id(self):
        return self.__hex_id
    
class TrackId(PlayableId, SpotifyId):
    pattern = re.compile("spotify:track:(.{22})")

    def __init__(self, hex_id):
        self.__hex_id = hex_id.lower()

    @staticmethod
    def from_uri(uri):
        search = TrackId.pattern.search(uri)
        if search is not None:
            track_id = search.group(1)
            return TrackId(
                util.bytes_to_hex(PlayableId.base62.decode(track_id.encode(), 16)))
        raise RuntimeError("Not a Spotify track ID: %s" % uri)

    @staticmethod
    def from_base62(base62):
        return TrackId(util.bytes_to_hex(PlayableId.base62.decode(base62.encode(), 16)))

    @staticmethod
    def from_hex(hex_str):
        return TrackId(hex_str)

    def to_mercury_uri(self):
        return "hm://metadata/4/track/%s" % self.__hex_id

    def to_spotify_uri(self):
        return "spotify:track:%s" % TrackId.base62.encode(util.hex_to_bytes(self.__hex_id)).decode()

    def hex_id(self):
        return self.__hex_id

    def get_gid(self):
        return util.hex_to_bytes(self.__hex_id)
    

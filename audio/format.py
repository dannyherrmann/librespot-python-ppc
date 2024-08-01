import metadata_pb2 as Metadata
from enum import Enum

class SuperAudioFormat(Enum):
    MP3 = 0x00
    VORBIS = 0x01
    AAC = 0x02

    @staticmethod
    def get(audio_format):
        if audio_format in [
                Metadata.AudioFile.OGG_VORBIS_96,
                Metadata.AudioFile.OGG_VORBIS_160,
                Metadata.AudioFile.OGG_VORBIS_320,
        ]:
            return SuperAudioFormat.VORBIS
        if audio_format in [
                Metadata.AudioFile.MP3_256,
                Metadata.AudioFile.MP3_320,
                Metadata.AudioFile.MP3_160,
                Metadata.AudioFile.MP3_96,
                Metadata.AudioFile.MP3_160_ENC,
        ]:
            return SuperAudioFormat.MP3
        if audio_format in [
                Metadata.AudioFile.AAC_24,
                Metadata.AudioFile.AAC_48,
                Metadata.AudioFile.AAC_24_NORM,
        ]:
            return SuperAudioFormat.AAC
        raise RuntimeError("Unknown audio format: {}".format(audio_format))
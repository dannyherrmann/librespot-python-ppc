from Crypto.Util import Counter
from Crypto.Cipher import AES
from .storage import ChannelManager
from structure import AudioDecrypt
import io
import time

def bytes_to_int(bytes):
    result = 0
    for b in bytes:
        result = result * 256 + ord(b)
    return result

class AesAudioDecrypt(AudioDecrypt):
    audio_aes_iv = b'r\xe0g\xfb\xdd\xcb\xcfw\xeb\xe8\xbcd?c\r\x93'
    cipher = None
    decrypt_count = 0
    decrypt_total_time = 0
    iv_int = bytes_to_int(audio_aes_iv)
    iv_diff = 0x100

    def __init__(self, key):
        self.key = key

    def decrypt_chunk(self, chunk_index, buffer):
        new_buffer = io.BytesIO()
        iv = self.iv_int + int(ChannelManager.chunk_size * chunk_index / 16)
        start = time.time()
        for i in range(0, len(buffer), 4096):
            cipher = AES.new(key=self.key,
                             mode=AES.MODE_CTR,
                             counter=Counter.new(128, initial_value=iv))
            count = min(4096, len(buffer) - i)
            decrypted_buffer = cipher.decrypt(buffer[i:i + count])
            new_buffer.write(decrypted_buffer)
            if count != len(decrypted_buffer):
                raise RuntimeError(
                    "Couldn't process all data, actual: {}, expected: {}".
                    format(len(decrypted_buffer), count))
            iv += self.iv_diff
        self.decrypt_total_time += (time.time() - start) * 1e9  # Convert to nanoseconds
        self.decrypt_count += 1
        new_buffer.seek(0)
        return new_buffer.read()

    def decrypt_time_ms(self):
        return 0 if self.decrypt_count == 0 else int(
            (self.decrypt_total_time / self.decrypt_count) / 1e6)  # Convert to milliseconds
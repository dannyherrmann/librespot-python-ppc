import binascii
import math
from Crypto.Random import get_random_bytes

def random_hex_string(length):
    buffer = get_random_bytes(int(length / 2))
    return bytes_to_hex(buffer)

def bytes_to_hex(buffer):
    return binascii.hexlify(buffer).decode()

def int_to_bytes(i):
    """
    Convert an integer to a byte(s)
    Args:
        i: Integer to convert
    Returns:
        bytes
    """
    width = i.bit_length()
    width += 8 - ((width % 8) or 8)
    fmt = '%%0%dx' % (width // 4)
    return b"\x00" if i == 0 else binascii.unhexlify(fmt % i)

class Base62:
    standard_base = 256
    target_base = 62

    def __init__(self, alphabet):
        self.alphabet = alphabet
        self.create_lookup_table()

    @staticmethod
    def create_instance_with_inverted_character_set():
        return Base62(Base62.CharacterSets.inverted)

    def encode(self, message, length=-1):
        indices = self.convert(message, self.standard_base, self.target_base, length)
        return self.translate(indices, self.alphabet)

    def decode(self, encoded, length=-1):
        prepared = self.translate(encoded, self.lookup)
        return self.convert(prepared, self.target_base, self.standard_base, length)

    def translate(self, indices, dictionary):
        translation = bytearray(len(indices))
        for i in range(len(indices)):
            translation[i] = dictionary[int.from_bytes(bytes([indices[i]]), "big")]
        return translation

    def convert(self, message, source_base, target_base, length):
        estimated_length = self.estimate_output_length(len(message), source_base, target_base) if length == -1 else length
        out = b""
        source = message
        while len(source) > 0:
            quotient = b""
            remainder = 0
            for b in source:
                accumulator = int(b & 0xff) + remainder * source_base
                digit = int((accumulator - (accumulator % target_base)) / target_base)
                remainder = int(accumulator % target_base)
                if len(quotient) > 0 or digit > 0:
                    quotient += bytes([digit])
            out += bytes([remainder])
            source = quotient
        if len(out) < estimated_length:
            size = len(out)
            for _ in range(estimated_length - size):
                out += bytes([0])
            return self.reverse(out)
        if len(out) > estimated_length:
            return self.reverse(out[:estimated_length])
        return self.reverse(out)

    def estimate_output_length(self, input_length, source_base, target_base):
        return int(math.ceil((math.log(source_base) / math.log(target_base)) * input_length))

    def reverse(self, arr):
        length = len(arr)
        reversed_arr = bytearray(length)
        for i in range(length):
            reversed_arr[length - i - 1] = arr[i]
        return bytes(reversed_arr)

    def create_lookup_table(self):
        self.lookup = {}
        alphabet_list = list(self.alphabet)  # Ensure alphabet is a list of integers or characters
        for i in range(len(alphabet_list)):
            self.lookup[alphabet_list[i]] = i & 0xff

    class CharacterSets:
        gmp = b'0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
        inverted = b'0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
        
def hex_to_bytes(s):
    """
    Convert a hexadecimal string to a byte array.
    
    :param s: A string containing hexadecimal digits.
    :return: A byte array.
    """
    return binascii.unhexlify(s)
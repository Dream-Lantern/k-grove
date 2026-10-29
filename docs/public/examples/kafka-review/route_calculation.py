"""Offline teaching calculation; NOT a producer or a cluster experiment.

Algorithm references: Apache Kafka 3.9.0 Utils.murmur2/toPositive and
librdkafka v2.8.0 rdkafka_msg.c, rdmurmur2.c. No third-party dependencies.
The constants in VECTORS come from librdkafka's unittest_murmur2.
"""

import json
import zlib


def murmur2(data: bytes) -> int:
    mask, m = 0xFFFFFFFF, 0x5BD1E995
    h = 0x9747B28C ^ len(data)
    end = len(data) // 4 * 4
    for start in range(0, end, 4):
        k = int.from_bytes(data[start:start + 4], "little")
        k = k * m & mask
        k ^= k >> 24
        k = k * m & mask
        h = ((h * m) & mask) ^ k
    tail = data[end:]
    if len(tail) >= 3:
        h ^= tail[2] << 16
    if len(tail) >= 2:
        h ^= tail[1] << 8
    if tail:
        h ^= tail[0]
        h = h * m & mask
    h ^= h >> 13
    h = h * m & mask
    h ^= h >> 15
    return h


VECTORS = {
    b"kafka": 0xD067CF64,
    b"giberish123456789": 0x8F552B0C,
    b"1234": 0x9FC97B14,
    b"234": 0xE7C009CA,
    b"34": 0x873930DA,
    b"4": 0x5A4B5CA1,
    b"PreAmbleWillBeRemoved,ThePrePartThatIs": 0x78424F1C,
    b"reAmbleWillBeRemoved,ThePrePartThatIs": 0x4A62B377,
    b"eAmbleWillBeRemoved,ThePrePartThatIs": 0xE0E4E09E,
    b"AmbleWillBeRemoved,ThePrePartThatIs": 0x62B8B43F,
    b"": 0x106E08D9,
}


if __name__ == "__main__":
    for vector, expected in VECTORS.items():
        assert murmur2(vector) == expected, vector
    rows = []
    for key in (b"order-42", b""):
        raw = murmur2(key)
        positive = raw & 0x7FFFFFFF
        crc = zlib.crc32(key)
        rows.append({
            "key_hex": key.hex(), "key_length": len(key),
            "murmur2_unsigned": raw, "murmur2_positive": positive,
            "java_partition_4": positive % 4,
            "c_murmur2_random_partition_4": positive % 4,
            "crc32_unsigned": crc,
            "c_consistent_random_partition_4": crc % 4 if key else "random/sticky path",
        })
    print(json.dumps({"status": "offline calculation only",
                      "source_vectors_passed": len(VECTORS), "rows": rows}, indent=2))

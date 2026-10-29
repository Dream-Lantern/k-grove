"""Synthetic fixed-frame PCM and in-memory playback contract, not an audio device."""
from array import array
from dataclasses import dataclass
import json
import math
import struct


@dataclass(frozen=True)
class AudioSpec:
    sample_rate: int = 16000
    frame_ms: int = 10
    channels: int = 1
    encoding: str = 'pcm_s16le'

    def __post_init__(self):
        if (self.sample_rate, self.frame_ms, self.channels, self.encoding) != (16000, 10, 1, 'pcm_s16le'):
            raise ValueError('this teaching example supports only 16kHz/10ms/mono/s16le')


def normalize_audio(data, *, representation, spec=AudioSpec()):
    """Explicit representation, never amplitude-based dtype guessing."""
    if representation == 'pcm_s16le':
        if not isinstance(data, (bytes, bytearray, memoryview)) or len(data) != 320:
            raise ValueError('need exactly 320 little-endian PCM bytes')
        samples = list(struct.unpack('<160h', data))
    elif representation == 'int16_values':
        if not isinstance(data, (list, tuple, array)) or len(data) != 160:
            raise ValueError('need exactly 160 scalar int16 values')
        samples = list(data)
        if any(type(x) is not int or not -32768 <= x <= 32767 for x in samples):
            raise ValueError('int16 scalar required')
    elif representation == 'normalized_float':
        if not isinstance(data, (list, tuple, array)) or len(data) != 160:
            raise ValueError('need exactly 160 normalized floats')
        if any(type(x) is not float or not math.isfinite(x) or not -1 <= x <= 32767/32768 for x in data):
            raise ValueError('finite normalized int16-range floats required')
        return list(data)
    else:
        raise ValueError('unknown explicit representation')
    return [x / 32768 for x in samples]


class EnergyGate:
    def __init__(self, threshold=.02, hold_ms=30):
        if not math.isfinite(threshold) or not 0 < threshold <= 1 or hold_ms <= 0 or hold_ms % 10:
            raise ValueError('need positive threshold and multiple-of-10ms hold')
        self.threshold, self.hold_ms, self.active_ms = threshold, hold_ms, 0

    def push(self, data, *, representation):
        values = normalize_audio(data, representation=representation)
        rms = math.sqrt(sum(x*x for x in values)/len(values))
        active = rms >= self.threshold
        self.active_ms = self.active_ms + 10 if active else 0
        return {'rms': rms, 'energy_active': active, 'active_ms': self.active_ms,
                'gate_triggered': self.active_ms >= self.hold_ms, 'speech_verified': False}


class PlaybackGuard:
    """ACK is injected by a simulated trusted player; no real audio is stopped.

    event IDs are single-use identities across generations in this demo session.
    No persistence, auth, distributed concurrency, or clock handling is provided.
    """
    def __init__(self):
        self.generation = 0
        self.state = 'IDLE'
        self.seen = {}
        self.pending_event = None
        self.played_samples = None

    def start(self, generation):
        if type(generation) is not int or generation <= self.generation:
            raise ValueError('generation must strictly increase')
        if self.state == 'CANCEL_REQUESTED':
            raise ValueError('wait for stop confirmation before starting in this demo')
        self.generation, self.state = generation, 'PLAYING'
        self.pending_event, self.played_samples = None, None

    def request_cancel(self, event_id, target_generation):
        if not isinstance(event_id, str) or not event_id or type(target_generation) is not int:
            return 'INVALID_IDENTITY'
        if event_id in self.seen:
            return 'DUPLICATE' if self.seen[event_id] == target_generation else 'IDENTITY_CONFLICT'
        self.seen[event_id] = target_generation
        if target_generation != self.generation:
            return 'STALE_GENERATION' if target_generation < self.generation else 'FUTURE_GENERATION'
        if self.state == 'CANCEL_REQUESTED':
            return 'CANCEL_PENDING'
        if self.state != 'PLAYING':
            return 'IDLE_NO_CANCEL'
        self.state, self.pending_event = 'CANCEL_REQUESTED', event_id
        return self.state

    def acknowledge_stopped(self, event_id, generation, played_samples):
        if (self.state != 'CANCEL_REQUESTED' or event_id != self.pending_event
                or generation != self.generation or type(played_samples) is not int or played_samples < 0):
            return 'ACK_REJECTED'
        self.state, self.played_samples = 'STOPPED', played_samples
        return self.state

    def snapshot(self):
        return {'generation': self.generation, 'state': self.state,
                'stop_confirmation': 'CONFIRMED' if self.state == 'STOPPED' else 'UNKNOWN',
                'played_samples': self.played_samples}

    def accepts_output(self, generation):
        return generation == self.generation and self.state == 'PLAYING'


def demo():
    waveform = [100, -100] * 80
    forms = [(waveform, 'int16_values'), (array('h', waveform), 'int16_values'),
             (struct.pack('<160h', *waveform), 'pcm_s16le'),
             ([v/32768 for v in waveform], 'normalized_float')]
    normalized = [normalize_audio(x, representation=r) for x, r in forms]
    noise_gate = EnergyGate()
    noise = [10000, -10000] * 80
    noise_results = [noise_gate.push(noise, representation='int16_values') for _ in range(3)]
    guard = PlaybackGuard()
    guard.start(1)
    statuses = [guard.request_cancel('e-1', 1), guard.request_cancel('e-1', 1)]
    without_ack = guard.snapshot()
    statuses.append(guard.acknowledge_stopped('e-1', 1, 12800))
    guard.start(2)
    statuses += [guard.request_cancel('e-1', 2), guard.request_cancel('e-old', 1)]
    idle = PlaybackGuard()
    statuses.append(idle.request_cancel('e-idle', 0))
    return {'data_kind': 'synthetic PCM and simulated player ACK',
            'samples': 160, 'bytes': 320,
            'representations_equal': all(v == normalized[0] for v in normalized),
            'low_rms': math.sqrt(sum(v*v for v in normalized[0])/160),
            'noise_gate': noise_results, 'events': statuses,
            'without_ack': without_ack, 'current_after_old_events': guard.snapshot()}


if __name__ == '__main__':
    print(json.dumps(demo(), ensure_ascii=False, indent=2))

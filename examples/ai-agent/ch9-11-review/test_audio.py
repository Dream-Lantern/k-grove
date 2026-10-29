from array import array
import math
import struct
import unittest

from audio_state import AudioSpec, EnergyGate, PlaybackGuard, demo, normalize_audio


class AudioTests(unittest.TestCase):
    def test_spec_and_equivalent_representations(self):
        self.assertEqual(AudioSpec().sample_rate, 16000)
        values = [100, -100]*80
        forms = [(values, 'int16_values'), (array('h', values), 'int16_values'),
                 (struct.pack('<160h', *values), 'pcm_s16le'),
                 ([x/32768 for x in values], 'normalized_float')]
        expected = [x/32768 for x in values]
        for data, rep in forms:
            with self.subTest(rep=rep):
                self.assertEqual(normalize_audio(data, representation=rep), expected)
        self.assertAlmostEqual(demo()['low_rms'], 100/32768)

    def test_bad_format_frames_and_samples_rejected(self):
        for kwargs in [{'sample_rate':8000}, {'channels':2}, {'frame_ms':20}, {'encoding':'float32'}]:
            with self.assertRaises(ValueError):
                AudioSpec(**kwargs)
        bad = [(b'\x00'*319, 'pcm_s16le'), (b'', 'pcm_s16le'),
               ([100]*159, 'int16_values'), ([32768]*160, 'int16_values'),
               ([[1]]*160, 'int16_values'), ([True]*160, 'int16_values'),
               ([float('nan')]*160, 'normalized_float'), ([float('inf')]*160, 'normalized_float'),
               ([1.5]*160, 'normalized_float'), ([0.0]*160, 'guess')]
        for data, rep in bad:
            with self.subTest(rep=rep, size=len(data)):
                with self.assertRaises(ValueError):
                    normalize_audio(data, representation=rep)

    def test_high_energy_noise_is_not_verified_speech(self):
        gate = EnergyGate(hold_ms=30)
        first = gate.push([10000,-10000]*80, representation='int16_values')
        self.assertTrue(first['energy_active'])
        self.assertFalse(first['gate_triggered'])
        gate.push([10000,-10000]*80, representation='int16_values')
        third = gate.push([10000,-10000]*80, representation='int16_values')
        self.assertTrue(third['gate_triggered'])
        self.assertFalse(third['speech_verified'])
        self.assertEqual(third['active_ms'], 30)
        self.assertEqual(gate.push([0]*160, representation='int16_values')['active_ms'], 0)

    def test_duplicate_and_identity_conflict(self):
        guard = PlaybackGuard(); guard.start(1)
        self.assertEqual(guard.request_cancel('e1', 1), 'CANCEL_REQUESTED')
        self.assertEqual(guard.request_cancel('e1', 1), 'DUPLICATE')
        self.assertEqual(guard.acknowledge_stopped('e1', 1, 12800), 'STOPPED')
        guard.start(2)
        self.assertEqual(guard.request_cancel('e1', 2), 'IDENTITY_CONFLICT')
        self.assertEqual(guard.state, 'PLAYING')

    def test_old_and_future_events_leave_current_reply(self):
        guard = PlaybackGuard(); guard.start(2)
        self.assertEqual(guard.request_cancel('old', 1), 'STALE_GENERATION')
        self.assertEqual(guard.request_cancel('future', 3), 'FUTURE_GENERATION')
        self.assertEqual(guard.state, 'PLAYING')
        self.assertFalse(guard.accepts_output(1))
        self.assertTrue(guard.accepts_output(2))

    def test_idle_does_not_cancel_or_discard_input(self):
        guard = PlaybackGuard()
        self.assertEqual(guard.request_cancel('idle', 0), 'IDLE_NO_CANCEL')
        self.assertEqual(guard.state, 'IDLE')

    def test_no_ack_is_unknown_and_late_audio_blocked(self):
        guard = PlaybackGuard(); guard.start(1)
        guard.request_cancel('e1', 1)
        self.assertEqual(guard.snapshot()['stop_confirmation'], 'UNKNOWN')
        self.assertIsNone(guard.snapshot()['played_samples'])
        self.assertEqual(guard.state, 'CANCEL_REQUESTED')
        self.assertFalse(guard.accepts_output(1))
        self.assertEqual(guard.request_cancel('e2', 1), 'CANCEL_PENDING')
        with self.assertRaises(ValueError):
            guard.start(2)

    def test_ack_must_match_pending_event_and_generation(self):
        guard = PlaybackGuard(); guard.start(1); guard.request_cancel('e1', 1)
        for args in [('wrong',1,10), ('e1',0,10), ('e1',1,-1), ('e1',1,True)]:
            self.assertEqual(guard.acknowledge_stopped(*args), 'ACK_REJECTED')
        self.assertEqual(guard.acknowledge_stopped('e1',1,12800), 'STOPPED')
        self.assertEqual(guard.snapshot()['stop_confirmation'], 'CONFIRMED')
        self.assertEqual(guard.played_samples/16000, .8)


if __name__ == '__main__': unittest.main()

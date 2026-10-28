"""Numerical recovery and rejection tests; no keys, devices, or persistent state."""
import itertools
import json
import math
from pathlib import Path
import sys
import unittest

import numpy as np
from scipy.signal import fftconvolve

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geometry
import probe


def image_arrivals(dimensions, position):
    """Independent forward oracle: enumerate image sources, no inverse identities."""
    room = np.array(dimensions, dtype=float)
    source = np.array(position, dtype=float)
    echoes = []
    for m in itertools.product((-1, 0, 1), repeat=3):
        for q in itertools.product((0, 1), repeat=3):
            order = sum(abs(2*m[k]-q[k]) for k in range(3))
            if not 1 <= order <= 2:
                continue
            image = 2*np.array(m)*room + (-1.0)**np.array(q)*source
            path = float(np.linalg.norm(image-source))
            echoes.append({"delay_ms": path/343.0*1000,
                           "strength": .82**order/(1+path)})
    return echoes


def image_recording(dimensions, position, seed):
    fs = 48000
    rir = np.zeros(int(.4*fs))
    rir[0] = 1
    for e in image_arrivals(dimensions, position):
        idx = e['delay_ms']*.001*fs
        sample = int(idx)
        fraction = idx-sample
        rir[sample] += e['strength']*(1-fraction)
        rir[sample+1] += e['strength']*fraction
    recording = fftconvolve(probe.probe_sweep(), rir)
    recording = np.pad(recording, (int(.12*fs), int(.15*fs)))
    recording = recording/np.max(np.abs(recording))*.65
    return recording + np.random.default_rng(seed).normal(0, 1e-5, len(recording))


class GeometryTests(unittest.TestCase):
    def assert_shape(self, candidates, dimensions, tolerance=.03):
        expected = sorted(dimensions, reverse=True)
        self.assertTrue(any(np.max(np.abs(np.array(c['dimensions_m'])-expected)) < tolerance
                            for c in candidates), (expected, candidates))

    def test_unlabelled_independent_image_source_recovery(self):
        # Three different room shapes; no true dimensions/labels go into solve_echoes.
        for dims, pos in [((5.7,4.3,2.9),(1.27,1.61,1.13)),
                          ((6.2,4.7,3.1),(1.41,1.83,1.19)),
                          ((4.8,3.7,2.6),(.87,1.29,1.02))]:
            with self.subTest(dimensions=dims):
                arrivals = image_arrivals(dims,pos)
                np.random.default_rng(21).shuffle(arrivals)
                candidates, _ = geometry.solve_echoes(arrivals)
                self.assert_shape(candidates,dims)

    def test_small_arrival_errors_and_outliers(self):
        arrivals = image_arrivals((5.7,4.3,2.9),(1.27,1.61,1.13))
        rng = np.random.default_rng(14)
        for e in arrivals:
            e['delay_ms'] += float(rng.uniform(-.018,.018))
        arrivals += [{'delay_ms':3.11,'strength':.025},
                     {'delay_ms':40.12,'strength':.02}]
        candidates, _ = geometry.solve_echoes(arrivals)
        self.assert_shape(candidates,(5.7,4.3,2.9))

    def test_audio_round_trip_and_repeatability(self):
        dims=(5.7,4.3,2.9); pos=(1.27,1.61,1.13)
        result=geometry.reconstruct([image_recording(dims,pos,seed) for seed in range(3)])
        self.assertEqual(result['status'],'candidate')
        self.assertEqual(result['source'],'recorded_audio')
        self.assert_shape(result['candidates'],dims)
        json.dumps(result, allow_nan=False)

    def test_second_identifiable_audio_shape(self):
        dims=(5.3,4.1,3.2); pos=(1.12,1.57,.94)
        result=geometry.reconstruct([geometry.synthetic_recording(dims,pos,seed=s) for s in range(3)])
        self.assert_shape(result['candidates'],dims)

    def test_two_coherent_layouts_remain_ambiguous(self):
        arrivals=image_arrivals((5.7,4.3,2.9),(1.27,1.61,1.13))
        arrivals+=image_arrivals((6.2,4.7,3.1),(1.41,1.83,1.19))
        candidates,_=geometry.solve_echoes(arrivals)
        self.assertGreaterEqual(len(candidates),2)
        self.assert_shape(candidates,(5.7,4.3,2.9))
        self.assert_shape(candidates,(6.2,4.7,3.1))

    def test_missing_wall_does_not_get_invented(self):
        # Six first echoes alone are not enough: second reflections must agree.
        e=geometry.synthetic_echoes()
        first_delays=[2*d/343*1000 for d in (1.27,4.43,1.61,2.69,1.13,1.77)]
        first=[p for p in e if min(abs(p['delay_ms']-d) for d in first_delays)<.001]
        candidates,_=geometry.solve_echoes(first)
        self.assertEqual(candidates,[])

    def test_silence_noise_and_single_capture_are_rejected(self):
        silence=np.zeros(4*48000)
        noise=np.random.default_rng(7).normal(0,.05,4*48000)
        for recordings in ([silence,silence], [noise,noise], [geometry.synthetic_recording()]):
            with self.subTest(recordings=len(recordings)):
                result=geometry.reconstruct(recordings)
                self.assertEqual(result['status'],'insufficient_evidence')
                self.assertEqual(result['candidates'],[])
                json.dumps(result,allow_nan=False)

    def test_inconsistent_captures_do_not_form_one_room(self):
        result=geometry.reconstruct([
            geometry.synthetic_recording((5.7,4.3,2.9),(1.27,1.61,1.13)),
            geometry.synthetic_recording((6.2,4.7,3.1),(1.41,1.83,1.19))])
        self.assertEqual(result['candidates'],[])

    def test_dense_random_echoes_cannot_cherry_pick_a_room(self):
        # Dense clutter can accidentally satisfy many pairwise timing identities.
        # Layout acceptance must also explain the observed signal as a whole.
        for seed in (1, 2, 8):
            with self.subTest(seed=seed):
                rng = np.random.default_rng(seed)
                echoes = [{'delay_ms': float(t), 'strength': float(a)}
                          for t, a in zip(rng.uniform(2,22,48), rng.uniform(.3,1,48))]
                candidates, diagnostics = geometry.solve_echoes(echoes)
                self.assertEqual(candidates, [])
                self.assertEqual(diagnostics.get('rejection_reason'), 'unexplained_early_echoes')

    def test_bounded_search_ignores_unlimited_outliers(self):
        echoes=[{'delay_ms':float(t),'strength':1.0}
                for t in np.random.default_rng(4).uniform(2,70,10000)]
        candidates,diag=geometry.solve_echoes(echoes)
        self.assertEqual(candidates,[])
        self.assertLessEqual(diag['hypotheses_tested'],math.comb(geometry.MAX_PAIRS,3))
        self.assertEqual(diag['echo_search_limit'],48)

    def test_invalid_audio_is_a_validation_error(self):
        for recordings,fs in [([],48000),([np.zeros(4*48000)]*4,48000),
                              ([np.zeros(100)],48000),([np.full(4*48000,np.nan)],48000),
                              ([np.zeros(4*16000)],16000),([np.zeros((4*48000,2))],48000)]:
            with self.subTest(fs=fs):
                with self.assertRaises(ValueError):
                    geometry.reconstruct(recordings,fs)

    def test_demo_is_explicitly_simulated(self):
        result=geometry.demo()
        self.assertEqual(result['source'],'synthetic_demo')
        self.assertIn('simulated',result['message'].lower())
        self.assert_shape(result['candidates'],(5.7,4.3,2.9))
        self.assertEqual(len(result['candidates'][0]['vertices']),8)
        self.assertEqual(len(result['candidates'][0]['faces']),6)


if __name__ == '__main__':
    unittest.main()

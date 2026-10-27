import numpy as np

from nimea_robot.audio import FS, a_wav, decodificar, remuestrear
from nimea_robot.vad import DetectorVoz, escuchar_frase


def _ruido(seg, nivel=0.002):
    return (np.random.default_rng(0).standard_normal(int(FS * seg)) * nivel).astype(np.float32)


def _voz(seg):
    t = np.arange(int(FS * seg)) / FS
    return (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_detecta_una_frase():
    audio = np.concatenate([_ruido(1), _voz(1.5), _ruido(1.5)])
    frases = DetectorVoz().alimentar(audio)
    assert len(frases) == 1
    assert 1.5 <= len(frases[0]) / FS <= 2.8


def test_el_ruido_no_dispara():
    assert DetectorVoz().alimentar(_ruido(3)) == []


def test_escuchar_frase_caduca_si_nadie_habla():
    trozos = iter([_ruido(0.1)] * 10)
    assert escuchar_frase(lambda: next(trozos, None), DetectorVoz(), espera_max=0.2) is None


def test_wav_ida_y_vuelta():
    pcm = _voz(0.5)
    assert np.allclose(decodificar(a_wav(pcm)), pcm, atol=1e-3)


def test_remuestrear():
    assert len(remuestrear(np.zeros(48000, dtype=np.float32), 48000, 16000)) == 16000

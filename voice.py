import re
import time
import numpy as np
import sounddevice as sd
from piper.voice import PiperVoice

try:
    from piper.config import SynthesisConfig
except ImportError:
    SynthesisConfig = None

MODEL_PATH = "#" #chemin brut du fichier onnx
CONFIG_PATH = "###" #chemin brut du fichier onnx.json

# Chargé une seule fois, au moment de l'import du module
_voice = PiperVoice.load(MODEL_PATH, config_path=CONFIG_PATH)


def _clean_text(text: str) -> str:
    """Nettoie le texte avant synthèse : enlève quelques symboles parasites,
    et convertit un 'h' entre deux chiffres (ex: '20h30') en ' heure ',
    sans toucher aux séparateurs décimaux (virgule/point)."""
    text = re.sub(r'[@#$^&*]', '', text)
    text = re.sub(r'(?<=\d)h(?=\d)', ' heure ', text)
    return text


def _chunk_to_int16_bytes(chunk) -> bytes:
    """Extrait les octets audio 16 bits d'un AudioChunk, quel que soit
    le nom exact de l'attribut dans cette version de piper-tts."""
    if hasattr(chunk, "audio_int16_bytes"):
        return chunk.audio_int16_bytes
    if hasattr(chunk, "audio_int16_array"):
        return chunk.audio_int16_array.tobytes()
    if hasattr(chunk, "audio_float_array"):
        arr = np.clip(chunk.audio_float_array, -1.0, 1.0)
        return (arr * 32767).astype(np.int16).tobytes()
    raise AttributeError(
        f"Format audio inattendu pour AudioChunk, attributs disponibles : {dir(chunk)}"
    )


def speak(text: str, length_scale: float = 0.9) -> None:
    """Génère et joue directement un texte avec la voix Piper.

    length_scale < 1.0 = débit plus rapide (1.0 = vitesse normale de la voix).
    """
    if not text:
        return

    cleaned = _clean_text(text)
    syn_config = SynthesisConfig(length_scale=length_scale) if SynthesisConfig else None

    t0 = time.time()
    audio_bytes = bytearray()
    sample_rate = None

    for chunk in _voice.synthesize(cleaned, syn_config=syn_config):
        if sample_rate is None:
            sample_rate = chunk.sample_rate
        audio_bytes.extend(_chunk_to_int16_bytes(chunk))

    t_synth = time.time() - t0

    samples = np.frombuffer(bytes(audio_bytes), dtype=np.int16)
    duree_audio = len(samples) / sample_rate
    print(f"⏱️  [Synthèse Piper] {t_synth:.2f}s pour {duree_audio:.2f}s d'audio généré")

    t0 = time.time()
    sd.play(samples, sample_rate)
    sd.wait()
    print(f"⏱️  [Lecture audio] {time.time() - t0:.2f}s")


if __name__ == "__main__":
    speak(input("Texte à dire : "))

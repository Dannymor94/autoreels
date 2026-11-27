"""Fixed, generated WAV assets for the isolated editor demo (not owner assets)."""
from autoreels.core.models import AudioAsset, BackgroundTrack

TRACKS = (
    AudioAsset(sha256="bc3958b6f5909418997f946676bb9212c473038d732790540f3f150c8e3113d9",
               label="Tone A", rights="synthetic", rights_note="Generated triangle wave, 250 Hz"),
    AudioAsset(sha256="2fb760b6b863eb3f0b8a575e72750c99705e1d1143c89308760c6ba8060fee1f",
               label="Tone B", rights="synthetic", rights_note="Generated triangle wave, 400 Hz"),
)

# track number, volume percent, fade flag (0 or 0.5 s), ducking flag
def soundtrack(code: tuple[int, ...] | None) -> BackgroundTrack | None:
    if code is None:
        return None
    if len(code) != 4:
        raise ValueError("invalid soundtrack preset")
    track, volume, fade, duck = code
    if track not in (1, 2) or volume not in (10, 20, 30) or fade not in (0, 1) or duck not in (0, 1):
        raise ValueError("invalid soundtrack preset")
    return BackgroundTrack(asset=TRACKS[track - 1], volume=volume / 100,
                           fade_seconds=fade * 0.5, ducking=bool(duck), final_normalize=True)

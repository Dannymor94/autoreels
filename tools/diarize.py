#!/usr/bin/env python3
"""M165: pyannote speaker diarization of one audio file → JSON {"turns": [[start, end, "SPEAKER_00"], …]}.
Runs in its OWN environment (torch + pyannote.audio, not project dependencies), e.g. ~/.venvs/m141:
    <python> tools/diarize.py <audio.wav> <out.json>
The Hugging Face token comes from HF_TOKEN (environment); the conditions of pyannote/speaker-diarization-3.1 and
pyannote/segmentation-3.0 must be accepted on huggingface.co. The token is never printed."""
import json
import os
import sys
import time


def main(wav: str, out: str) -> int:
    tok = os.environ.get("HF_TOKEN")
    if not tok:
        print("ошибка: нет HF_TOKEN", file=sys.stderr)
        return 2
    import torch
    from pyannote.audio import Pipeline
    try:
        pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=tok)
    except TypeError:
        pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=tok)
    if pipe is None:
        print("ошибка: модель не выдана — условия на huggingface.co не приняты", file=sys.stderr)
        return 2
    dev = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
    pipe.to(torch.device(dev))
    t = time.time()
    res = pipe(wav)
    ann = getattr(res, "speaker_diarization", res)
    turns = [[round(s.start, 3), round(s.end, 3), str(k)] for s, _, k in ann.itertracks(yield_label=True)]
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"turns": turns, "device": dev, "sec": round(time.time() - t, 1)}, fh)
    print(f"реплик {len(turns)}, говорящих {len({x[2] for x in turns})}, {time.time() - t:.0f} с на {dev}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))

"""Test-only foreground render child; not a public command or live worker."""
import sys
from pathlib import Path

from autoreels import __main__ as cli


def main():
    root, stem, clip, gate = sys.argv[1:]
    root = Path(root)
    # This fixture is deliberately restricted to the generated test clip.
    if (stem, clip, gate) != ("DEMO", "r01", "ui-ffmpeg"):
        raise ValueError("unsupported synthetic fixture")
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected git pull or source archive")
    cli._git_pull = forbidden
    cli._archive_video = forbidden
    outputs = cli.cmd_render(
        root=root, _manifest_paths=[root / "reviews" / (stem + ".review.json")],
        reels_filter=clip, gate_name=gate, profile="h264", encoder="libx264",
        pull_first=False, archive_source=False, fallback=False, allow_stale=False,
        auto_recrop=False, _raise_on_failure=True,
    )
    expected = root / "reels-out" / stem / "_gate" / gate / (clip + ".mp4")
    if list(outputs) != [expected]:
        raise RuntimeError("unexpected synthetic output")


if __name__ == "__main__":
    main()

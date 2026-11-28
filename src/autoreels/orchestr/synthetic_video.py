"""One original generated video-only fixture."""
from autoreels.core.models import VideoAsset

VIDEO_NAME = "synthetic-broll.mp4"
VIDEO = VideoAsset(
    sha256="56a6ad8e7171960b4bf1058b86590ea63289d1ceaefafbe564fc9ab95541c530",
    label="Generated red then blue video",width=36,height=64,duration_ms=1000,
    rights="synthetic",rights_note="Generated solid-color frames; no external media",
)

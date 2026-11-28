"""One generated still-image fixture; never discovers user media."""
from autoreels.core.models import ImageAsset

IMAGE_NAME = "synthetic-graphic-image.png"
IMAGE = ImageAsset(
    sha256="664b7f0bb3086e05fdd5bc8d5ca72ab3880076ed46903d61f827d3ef54599fd1",
    label="Generated two-color image", width=36, height=64,
    rights="synthetic", rights_note="Generated RGB test pattern; no external media",
)

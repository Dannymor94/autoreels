#!/bin/sh
# Системные пакеты для тестов в GitHub Actions (Ubuntu). Рендера там нет — нужен только ffmpeg/ffprobe.
set -e
sudo apt-get update -q
sudo apt-get install -y -q ffmpeg

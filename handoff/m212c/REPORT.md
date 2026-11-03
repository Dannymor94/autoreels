M212C — IMPLEMENTED, MEASURED
Коммит: 5695ccd; pytest: 2700 passed (было 2691+1)
Gamebox: integrity.txt 1, ERROR.mp4 3 (ffmpeg 8.0.1-3ubuntu2)
Сбойный h264 найден: reels-out/prew_isaev_anna/_gate/ab192/r03.ERROR.mp4
  маленький пакет: pts 54.921533 с, размер 12 байт, последний в потоке
  NAL nal_unit_type=6 (SEI — не AUD/EOS, как ожидалось)
  полное декодирование: ошибки — "missing picture in access unit", "no frame!", "Invalid data found when processing input"
  кадров/пакетов: 4119/4120 (один кадр потерян)
r14.ERROR.mp4 (m179diag) и r01.ERROR.mp4 (danny ab192): пакеты чисты, ошибок нет

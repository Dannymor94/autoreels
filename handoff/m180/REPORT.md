# REPORT M180

Коммит `08a2e45` (запушен):
> Render (M180): a clip failing the integrity check is kept as .ERROR.mp4 with ffmpeg's words in <rid>.integrity.txt, not deleted (m179: m165's gamebox message could not be examined)

pytest: **2566 passed** (1 новый `test_integrity_failure_keeps_the_clip_as_error_file`), 16 skipped, 9 deselected.

Клип, не прошедший проверку, теперь сохраняется как `rNN.ERROR.mp4` и рядом пишется `rNN.integrity.txt` с полным выводом ffmpeg. Остальные клипы — как раньше.

Статус: IMPLEMENTED.

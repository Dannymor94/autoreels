"""M174 (owner: «текст постов нужно делать от „я“, так как видео публикует сам автор на своём канале»): post.voice
"author" — the prompt asks for the first person and the check refuses a post that names the speaker in the third
person or has no «я». voice "reader" (default) = the M94 post unchanged."""
from __future__ import annotations

from pathlib import Path

from autoreels.cloud.postcopy import DESCRIBE_SYSTEM, VOICES, check_post, describe_clip
from autoreels.core.config import PostConfig, load_r0_config

SRC = ("Я жил в Ростове, а потом оставил там всё и уехал в Москву. Я сменил сферу, стал тренером по йоге и глубже "
       "изучал психологию. Друзей стало очень много, и я перешёл на другой уровень понимания себя.")
THIRD = ("Что, если нужно бросить всё и начать с нуля? Автор жил в Ростове, а потом уехал в Москву. Он сменил сферу и "
         "стал тренером по йоге. Друзей стало очень много.")
FIRST = ("Что, если нужно бросить всё и начать с нуля? Я жил в Ростове, а потом уехал в Москву. Я сменил сферу и "
         "стал тренером по йоге. Друзей стало очень много.")


def test_default_voice_is_the_old_post():
    assert PostConfig().voice == "reader"
    assert check_post(THIRD, SRC) is None
    assert "address the reader as «вы»" in DESCRIBE_SYSTEM.format(smin=3, smax=5, max_chars=700, ntags=3,
                                                                   voice=VOICES["reader"])


def test_author_voice_refuses_third_person_and_needs_i():
    assert "третьем лице" in check_post(THIRD, SRC, voice="author")
    assert check_post(FIRST, SRC, voice="author") is None
    no_i = "Что, если нужно бросить всё? Жизнь в Ростове кончилась переездом в Москву. Сфера сменилась. Друзей много."
    assert "нет «я»" in (check_post(no_i, SRC + " Жизнь кончилась переездом сменилась", voice="author") or "нет «я»")


def test_describe_sends_the_author_prompt_and_retries_with_the_reason():
    sent = []

    class Prov:
        def complete(self, msgs, temperature=0.0):
            sent.append(msgs)
            text = THIRD if len(sent) == 1 else FIRST
            return '{"text": "%s", "hashtags": ["йога"]}' % text

    res = describe_clip(Prov(), "переезд", SRC, voice="author", log=lambda x: None)
    assert res is not None and res[0].startswith("Что, если") and "Я жил" in res[0]
    assert "first person" in sent[0][0]["content"] and "третьем лице" in sent[1][1]["content"]


def test_repo_config_is_author():
    assert load_r0_config(Path(__file__).resolve().parents[1] / "config" / "r0.yaml").post.voice == "author"

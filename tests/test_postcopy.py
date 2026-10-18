"""M94: the post under a reel — a detailed description in the reel's words and hashtags said in it (owner: «нужно
делать подробное описание видео для постинга»); arl describe writes <rid>.post.txt, arl crosspost takes it."""
from __future__ import annotations

import csv
import io
import json

from autoreels import __main__ as cli
from autoreels.cloud.postcopy import check_hashtags, check_post, describe_clip, post_text
from tests.test_montage import _source

SRC = ("Почему подросток надевает маску? Чтобы выжить в семье, в обществе, нам приходится надевать маски. "
       "Маска защищает ребёнка от боли, но взрослому она мешает быть собой. Снять маску можно, когда есть доверие.")
GOOD = ("Почему подросток надевает маску? Чтобы выжить в семье и обществе, ребёнку приходится защищаться. "
        "Маска защищает от боли, но взрослому мешает быть собой. Снять её можно, когда появляется доверие.")


class Answers:
    name = "scripted"

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def complete(self, messages, temperature=0.0):
        self.calls.append(messages)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)


def test_the_post_stays_in_the_reel_words_and_size():
    assert check_post(GOOD, SRC) is None
    assert "предложений 1" in check_post("Почему подросток надевает маску?", SRC)
    assert "число 7" in check_post(GOOD.replace("ребёнку", "в 7 лет ребёнку"), SRC)
    assert "не из ролика" in check_post("Квантовая физика объясняет вселенную. Энергия вибраций решает проблемы. "
                                        "Медитация открывает чакры мгновенно.", SRC)
    assert "хэштег" in check_post(GOOD + " #маска", SRC) and "длиннее" in check_post(GOOD, SRC, max_chars=100)
    assert check_hashtags(["#Маска", "подросток", "доверие", "психология", "маска", "12"], SRC) == \
        ["маска", "подросток", "доверие"]                       # «психология» is not said; repeats and numbers go


def test_describe_retries_once_with_the_reason_then_gives_up():
    prov = Answers({"text": "Коротко.", "hashtags": []}, {"text": GOOD, "hashtags": ["маски", "доверие", "космос"]})
    assert describe_clip(prov, "Маска защищает", SRC, log=lambda m: None) == (GOOD, ["маски", "доверие"])
    assert "rejected: предложений 1" in prov.calls[1][-1]["content"]
    assert describe_clip(Answers("нет", "нет"), "", SRC, log=lambda m: None) is None
    assert describe_clip(Answers(TimeoutError("t")), "", SRC, log=lambda m: None) is None
    assert post_text(GOOD, ["маски", "доверие"], ["#Психология", "маски"]) == GOOD + "\n\n#психология #маски #доверие\n"


def test_cmd_describe_writes_post_files_and_crosspost_takes_them(tmp_path, capsys):
    _source(tmp_path)
    g = tmp_path / "reels-out" / "v" / "_gate" / "m88"
    g.mkdir(parents=True)
    for rid in ("r01", "r02", "r03"):
        (g / f"{rid}.mp4").write_bytes(b"clip")
    (g / "r01.transcript.txt").write_text(SRC, encoding="utf-8")
    (g / "r01.txt").write_text("Маска защищает ребёнка.\n", encoding="utf-8")
    (g / "r02.transcript.txt").write_text(SRC, encoding="utf-8")
    (g / "r02.txt").write_text("Подпись два.\n", encoding="utf-8")
    prov = Answers({"text": GOOD, "hashtags": ["маски"]}, "нет", "нет")
    assert cli.cmd_describe("v", root=tmp_path, gate="m88", provider=prov) == 0
    out = capsys.readouterr().out
    assert (g / "r01.post.txt").read_text(encoding="utf-8") == GOOD + "\n\n#маски\n"
    assert not (g / "r02.post.txt").exists() and "пропущен r02: описание не принято" in out
    assert "пропущен r03: нет r03.transcript.txt" in out and "описаний 1 из 3" in out
    assert "Caption: Маска защищает ребёнка." in prov.calls[0][-1]["content"]
    assert cli.cmd_describe("v", root=tmp_path, gate="m88", reels="r01", provider=Answers()) == 0   # kept
    assert "уже есть" in capsys.readouterr().out
    assert cli.cmd_crosspost("v", root=tmp_path, gate="m88") == 0
    rows = list(csv.reader(io.StringIO((tmp_path / "export" / "crosspost" / "v_m88.csv").read_text(encoding="utf-8-sig")),
                           delimiter=";"))
    assert rows[1] == ["v/r01.mp4", GOOD + "\n\n#маски", "пост"] and rows[2] == ["v/r02.mp4", "Подпись два.", "пост"]

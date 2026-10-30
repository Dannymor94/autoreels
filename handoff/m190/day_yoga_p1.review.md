# AutoReels block review
# source: manifests/day_yoga_p1.json
# blocks: 13  |  filter_removed: 3
# fingerprint: 2ba665544609b20e
# format: compact
#
# Score each block 0-100 for standalone short-video quality.
# Leave weak blocks unscored (omit the number).
#
# 80-100  complete thought, self-contained opening, quotable line,
#         payoff or closed question-answer arc
# 60-79   complete but unremarkable
# blank   broken thought, dangling reference, organisational talk,
#         or a speaker change that breaks the thought
#
# Pause markers after a sentence (speaker actually stopped there):
#   ⏸N.N   gap of N.N seconds — noticeable stop, decent ending point
#   ⏸⏸N.N  gap of N.N seconds — long stop, natural phrase end (best e: target)
# An e: on a sentence followed by ⏸⏸ gives a clip that ends where the speaker stopped.
#
# Merge markers (a thought split across blocks — score the block it belongs to):
#   +   after the score: join with the NEXT block
#   ++  after the score: join with the next TWO blocks (a thought across three)
#   -   before the score: join with the PRECEDING block (attach a run-up)
# A forward '+' on a block and a backward '-' on the next name the same join — counted once.
#
# Speed marker (after all other markers): @N.NN requests that speed for this clip.
#   80@1.15   play this clip 15% faster (subtitle sync adjusted automatically)
#   80+@1.1   join with next AND speed up 10%
# Allowed range 1.0-1.3 (content policy; atempo itself accepts 0.5-100 without chaining).
# Clips that exceed the manual ceiling get the minimum speed that fits, within that range.
#
# Optional fields after the score, introduced by '|' (each independent):
#   s:N   start at sentence N of the selection (sentences are numbered [1] [2]… below)
#   e:N   end at sentence N (numbering is continuous across a merge)
#   x:N,M,N-M  exclude sentences by number: cut them out and join what remains.
#              Example: s:3 e:12 | x:7,9-10  keeps sentences 3-12 minus 7, 9, 10.
#   h:N   cold open: play sentence N first as a teaser. Default: replays in the body only
#              if the sentence starts in the second half (hook_replay_min_pos).
#              h:N! — force replay. h:N- — force removal (plays once).
#   c:N,M,N-M  close shot on sentences — the line that should land (two_shot: true only).
#              Same numbering as s:/e:/x:. Example: 9 85 | c:3
#   k:N=word1,word2[;M=word3]  stress key words — 1–2 words that carry the meaning.
#              Case-insensitive, ё→е, *=prefix. Example: 11 90 | k:4=страх,сигнал
#   t: …  overlay this title on the first seconds of the clip  (second-to-last field)
#   d: …  post caption: 1-2 sentences shown under the clip when posted  (LAST field)
# Omit s:/e: and the clip starts at the first clean sentence and ends before trailing
# wind-down ('да', 'вот', 'как-то так'). Unknown/garbled fields are ignored, not fatal.
#
# Reply with ONLY lines of:  <number> [-]<score>[+|++][@speed] [| s:N] [| e:N] [| x:…] [| h:N] [| c:…] [| k:N=words] [| t: text] [| d: text]
# No commentary, no restating of text.  Example:
#   3 85+            (join 3 with 4)
#   5 -90           (join 5 back into 4)
#   7 72++          (join 7 with 8 and 9)
#   8 90@1.15       this clip at 1.15x
#   9 90 | s:2 e:9  start at sentence 2, end at sentence 9
#   9 85 | s:7 | e:14 | x:9,10  keep sentences 7-14, drop 9 and 10 from the middle
#   11 88 | h:3 | t: Ты не поломан — ты забыл свою силу   (default: position rule for replay)
#   11 88 | h:3!         sentence 3 opens AND stays in the body (force replay)
#   11 88 | h:3-         sentence 3 opens, always removed from body (force removal)
#   12 85 | t: Страх — это не страх, а сигнал | d: Тело подаёт сигнал, а мы принимаем его за страх.
#   5 90 | c:3          close shot on sentence 3 (the line that lands)
#   8 87 | k:2=страх   stress the word 'страх' in sentence 2
#
# Beat reordering (human review only): play sentences in a custom order.
# Add '> N' lines after the score line, one per sentence to play:
#   9 85 | s:1 e:6
#   > 4
#   > 2
#   > 5
# Each > N plays sentence N from the clip span. Sentences not listed are dropped.
# Gaps between beats are filled with brief silence (beat_gap_sec from config).
#
# Sentence completeness: [k]…→ marks an incomplete sentence (no terminal . ? !,
# or ends with a hanging phrase like 'потому что' / 'для того, чтобы').
# Never end a clip (e:) on a sentence marked …→.
# Put the strongest complete sentence LAST (use > lines if needed).
#
# ↗ after a sentence: the voice stays UP at its end — the speaker goes on, it sounds unfinished.
#   A weak e: target: end on a sentence without ↗ (measured from the audio, arl prosody).
#

1 | 28.5s | [1]…→ знаете, мне очень важно, для вас будет... ⏸1.0 [2] Да, обратная связь. ↗ ⏸0.3 [3] На самом деле вы просто дадите возможность автору сделать печатный вариант. [4] Вы, во-первых, поправите эту книгу, но, во-вторых, у меня будут деньги, потому что там меньше сотки. [5] Сейчас выпустить книжку невозможно просто. [6] И то я там ничего не заработаю. [7] Это просто чтобы она была в печатном варианте. ⏸0.4 [8] И кто купит, ну хрен с ним. [9] Я вам подарю этот печатный даже формат. ⏸0.6 [10] Вот кто здесь.
2 | 23.6s | [1] Мы все сделаем. ⏸0.4 [2] Кстати, вот тут музыкант говорит, что музыканты из группы Эфир, возможно, мне помогут наложить туда какую-то музыку. [3] Вы же знаете, да. ⏸⏸3.6 [4] Я не знаю, но если они будут с меня, там что-то требовать будут. ↗ ⏸⏸3.6 [5] Никогда не писал книги, никогда не думал, что так. ↗
3 | 85.8s | [1] Никогда не позвала на участие. ⏸0.5 [2] Ну если так, 15 лет, ну наверное так вот полгода, наверное, я ее пишу в таком формате. ⏸0.7 [3] Последний месяц я сижу и до утра сидел. ⏸⏸30.2 [4] Ваши нервные системы уникальны. ⏸0.6 [5] Вы здесь не просто так. [6] Раз вы живы, вы находитесь в этом теле, дайте себе место. ⏸1.0 [7] Дайте себе место в этом мире. ⏸⏸1.6 [8] Позвольте себе быть. ⏸0.5 [9] Реально. ⏸0.6 [10] Позвольте себе быть такой, как мы говорили на тренингах, будьте самими собими. ⏸⏸1.8 [11] Любимая наша фраза. ⏸1.2 [12] Прекратите на себя реально давить. ⏸0.5 [13] Просто увидите, что вы перенапрягаетесь.
4 | 25.4s | [1] Вы в напряжении. [2] Вот даже последнюю практику, которую можно сделать, просто можно как проверить, что вы в напряжении находитесь, что у вас нервная система зажата. [3] Вот просто сядьте, может быть прямой позвоночник. [4] Давайте вот последняя наша история. ⏸1.3 [5] Вы вытягиваетесь макушечкой вверх, можно лечь, да, просто вот лечь. ⏸1.3 [6] И можно одну ручку сюда положить, другую ручку сюда можно положить, да.
5 | 21.1s | [1] Скорее всего, если вы дышите грудью, то у вас нервная система напряжена. ↗ ⏸⏸3.2 [2] Сейчас посмотрите в тело, закройте глазки еще раз. ⏸0.3 [3] Посмотрите, что в теле, скорее всего, есть какое-то хроническое напряжение. ⏸⏸3.2 [4] Есть какое-то хроническое напряжение.
6 | 35.5s | [1] То есть там, где у вас уже год напряжения, 5, 10, 20, 30, посмотрите, тело само вам подскажет, есть там напряжение или нет. ⏸⏸5.5 [2] Но вы идете туда не так, чтобы вы взяли и отрезали этот кусок. ⏸0.6 [3] Вы не хотите избавиться от этого ощущения. ⏸⏸1.7 [4] Смотрите на это ощущение. ⏸1.2 [5] Какое оно занимает место? [6] Может быть в груди, в животе, в голове, в правом локте. [7] Просто почувствуйте это сейчас.
7 | 18.1s | [1] Может быть оно давит изнутри наружу. [2] Может быть наоборот, сжимается. ⏸⏸1.8 [3] Какого-то цвета, теплое или холодное. ⏸⏸1.7 [4] Какой-то плотности. ⏸0.9 [5] И возможно здесь живет какое-то чувство или какая-то эмоция.
8 | 41.6s | [1] Вот сейчас у вас нет желания избавиться от этого ощущения. ⏸1.4 [2] Вы наоборот идете в это ощущение с любовью, с заботой. [3] Представьте, что там ребенок, ваш ребенок. ⏸1.2 [4] Представьте своего ребенка там. ⏸0.8 [5] Как это ощущение? ⏸1.3 [6] Этот ребенок заболел, он сжался, он лежит в больнице. ⏸0.5 [7] Неужели бы вы его бросили? ⏸0.6 [8] Неужели бы вы его оставили? ⏸⏸1.6 [9] Вы бы сидели рядышком, правильно? ⏸⏸1.7 [10] И чем на самом деле можно излечить ребенка? [11] Конечно, можно таблетками ищем. [12] Мама чем лечит ребенка?
9 | 36.6s | [1] Или папа чем? ⏸0.6 [2] Ну, что он, конечно, совершенно верно. ⏸0.4 [3] Вот ваше внимание сейчас пускай туда идет в это ощущение с любовью и заботой. ⏸⏸2.9 [4] Теплое, дружелюбное, любящее присутствие. [5] Пускай будет в этом ощущение. [6] Просто позвольте. ⏸⏸3.3 [7] Не ожидайте, что это ощущение сразу пройдет. ⏸0.6 [8] Ничего не ожидайте. ⏸0.7 [9] Будьте как у больного ребеночка рядом, возле кроватки. [10] Просто побудьте. ⏸1.2 [11] Побудьте в этом ощущении какое-то время.
10 | 25.5s | [1] Просто побудьте. ⏸1.1 [2] Ваше внимание с любовью и заботой. ⏸0.9 [3] Возможно, вы сейчас увидите там маленького ребенка, себя. ⏸1.0 [4] Не знаю, может быть, 5, 7, 10 лет. ⏸1.1 [5] Посмотрите на нее, на него. ⏸1.0 [6] Что вы чувствуете к этому ребенку? ⏸1.5 [7] Возможно, прямо сейчас вам хочется его обнять. ⏸0.7 [8]…→ Может быть, он попал в какую-то ситуацию, и вам хочется помочь этому ребенку,
11 | 26.7s | [1] чтобы он был в безопасности. [2] Сделайте сейчас все для него, чтобы ему было хорошо. ↗ ⏸⏸1.6 [3] Он себя чувствовал в безопасности. ⏸1.1 [4] Если вы не видите ребенка, просто дайте в это ощущение любовь, заботу, тепло и внимание. ⏸0.6 [5] Свет своего внимания. ⏸0.8 [6] И побудьте в этом ощущении. ⏸0.7 [7] Никуда не убегайте. ⏸1.3 [8] Просто побудьте.
12 | 50.8s | [1] И этот взрослый, любящий, часть психики становится больше, и этот взрослый может дать вашему внутреннему ребенку то, что не дала мама, не долюбила, не доласкала. [2] Понятно? ⏸0.8 [3] Не дали подростку, возможно, что не поддержал где-то папа. ⏸0.5 [4] Ну, сказал, да нет, ты какой-то не такой. ⏸0.6 [5] Вот все пацаны там играют в футбол классно, а ты не очень. ⏸0.8 [6] Здесь вы даете своему подростку какую-то поддержку. ⏸⏸2.0 [7] Вы же своей психикой, своей любящей частью, которая становится больше, чем та часть, которая боится, гневается, обижается.
13 | 41.6s | [1] Понятно? ⏸0.6 [2] Осознанное. ⏸0.6 [3] И вы останавливаете эту реальность, реакцию автоматическую. ⏸0.4 [4] Чем? ⏸0.8 [5] Выбором. [6] Вы выбираете что? ⏸0.9 [7] Не эмоционировать? ⏸1.1 [8] Не быть в состоянии «я в жопе»? ⏸⏸1.8 [9] Да, совершенно верно. ⏸0.8 [10] А быть что? [11] Вы выбираете что-то другое. ⏸0.4 [12] То, что действительно вы. ⏸0.7 [13] Где вы хотите жить? [14] Тогда у вас появляется выбор. ⏸1.0 [15] Зачем жить в негативных эмоциях, а потом и реакциях, мыслях и так далее? ⏸⏸3.2 [16] То есть у вас появляется что? ⏸0.7 [17] Выбор. [18] У взрослого есть выбор. ⏸0.5 [19]…→ В

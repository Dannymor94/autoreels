M191 — IMPLEMENTED, MEASURED (гейт не объявляется)
Коммит: 7ce87c9; pytest: 32 passed в test_gatescore.py (было 30, +2 новых; полный suite — 2613+2=2615)

Часть 1: применено источников 7/7 (пропущено: нет); клипов эталона: 62 из 64; закомментировано по 1а:
  prew_isaev_danny M6 (r06: last subtitle 'силу».' != planned last word 'идти.') → 12 клипов
  disko_beach_p1 M4 (r04: seam inside word — cut at 1019.252s splits 'сталкивания') → 7 клипов
reviews/ после: только *_ref191.review* — да (плюс .git/ объекты handoff-ветки, не в рабочем дереве)
предупреждения эталона (warn.txt):
  prew_isaev_anna:   2 no room; 2 [ERROR] last word overlaps; 1 weak start
  prew_isaev_danny:  5 no room; 4 weak start; 2 [ERROR] last word overlaps; 1 short shot
  day_yoga_p1:       чисто
  day_yoga_p2:       5 no room; 2 weak start; 1 short shot
  disko_beach_p1:    1 weak start; 1 no room
  disko_beach_p2:    2 weak start; 1 short shot; 1 no room; 1 [ERROR] last word overlaps
  disko_beach_p3:    1 short shot

Часть 2: тесты: test_coverage_reports_missed_and_best, test_coverage_best_none_without_overlap; вывод без --ref без изменений — да

Часть 3: ИТОГО ref191 — 62 | 47.9 | 45 | 10 | 8 | 0 | 3 | 1.2 | 4.8 | 3 | 4 | 0 | 44 | 19 | 76 | 58 | 29/56
         ИТОГО m183   — 69 | 49.2 | 46 | 4 | 13 | 1 | 1 | 1.5 | 3.5 | 0 | 0 | 0 | 48 | 26 | 75 | 72 | 36/56
         разница      — -7 | -1.3 | -1 | +6 | -5 | -1 | +2 | -0.3 | +1.3 | +3 | +4 | 0 | -4 | -7 | +1 | -14
         эталон в m183: найдено 40 из 62; по источникам: day_yoga_p1 3/3, day_yoga_p2 8/16, disko_beach_p1 7/7, disko_beach_p2 4/6, disko_beach_p3 8/10, prew_isaev_anna 5/8, prew_isaev_danny 5/12
         m183 в эталоне: найдено 40 из 69
         согласие эталона с владельцем (покрытие владельца у ref191): 29/56 (52%)
         потерянные клипы эталона: (22 клипа — полный список в ref_in_m183.txt)
           day_yoga_p2: r02 «За болью сидит дар» нет_перекр, thesis→thesis→address→explanation | нет_вывода
           day_yoga_p2: r05 «Маска «контролёр»» r10 39%, explanation→thesis→explanation→explanation | нет_вывода
           day_yoga_p2: r08 «Вы давите на себя сами» нет_перекр, explanation→explanation→conclusion→explanation
           day_yoga_p2: r09 «Как снять с себя давление» нет_перекр, address→address→address | нет_вывода
           day_yoga_p2: r12 «Зазор между триггером и реакцией» r04 46%, question→explanation→conclusion→explanation | обрывок
           day_yoga_p2: r13 «Взрослый уважает свою судьбу» r04 43%, example→metaphor→thesis | нет_вывода
           day_yoga_p2: r15 «Лифт вашей психики» нет_перекр, metaphor→explanation→question→thesis→metaphor | ссылка_назад, нет_вывода
           day_yoga_p2: r16 «Сделайте по-другому» нет_перекр, address→example→thesis | нет_вывода, тем=2
           disko_beach_p2: r01 «Вы не поломаны» r06 49%, explanation→thesis→example→address→explanation | нет_вывода, тем=2
           disko_beach_p2: r05 «Среда держит ваши реакции» нет_перекр, thesis→explanation→conclusion
           disko_beach_p3: r04 «Причёсанная нервная система» нет_перекр, example→example→explanation | нет_вывода, тем=2
           disko_beach_p3: r10 «Ваш ресурс не безграничен» нет_перекр, question→example→example→explanation→thesis | нет_вывода
           prew_isaev_anna: r01 «Я всё бросил и уехал» нет_перекр, example×5 | нет_вывода
           prew_isaev_anna: r02 «Почему психолог не даёт советов» нет_перекр, thesis→thesis | нет_вывода, тем=2
           prew_isaev_anna: r06 «Почему мы врём» r06 45%, explanation→thesis | нет_вывода
           prew_isaev_danny: r01 «Ключ от закрытого шкафа» r06 39%, example→example | нет_вывода
           prew_isaev_danny: r02 «Все методы правы» нет_перекр, explanation→metaphor→metaphor | ссылка_назад, нет_вывода
           prew_isaev_danny: r03 «Главная потребность человека» r05 47%, thesis→thesis | нет_вывода
           prew_isaev_danny: r05 «Внутренний телефон» нет_перекр, example→explanation→explanation | нет_вывода, тем=2
           prew_isaev_danny: r06 «Страх — это сигнал» нет_перекр, thesis→metaphor | нет_вывода
           prew_isaev_danny: r07 «Зачем нужен стресс» нет_перекр, explanation→conclusion→conclusion
           prew_isaev_danny: r11 «Как родилась книга» нет_перекр, explanation→example→example | нет_вывода

Пропущено/не совпало:
  - команда grep -A80 "эталон m183 в ref191" не сработала (текст на русском «Эталон»): tee в m183_in_ref.txt выполнен отдельно, файл полный
  - 2 закомментированных клипа (M6 prew_isaev_danny, M4 disko_beach_p1) не вошли в эталон

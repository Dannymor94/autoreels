# M133 — static scan (assistant, vulture 60%, main c9bd55a)

## A. Unused anywhere (src + tests) — candidates for dead code

- src/autoreels/__main__.py:2685: unused import '_Seg'
- src/autoreels/__main__.py:5725: unused import '_Segment'
- src/autoreels/__main__.py:5866: unused variable 'dropped_blks'
- src/autoreels/__main__.py:5949: unused import '_wis'
- src/autoreels/cloud/autocut.py:550: unused variable 'Judge'
- src/autoreels/cloud/blocks.py:477: unused variable 'falloff_end'
- src/autoreels/cloud/blocks.py:487: unused import '_BSC'
- src/autoreels/cloud/label.py:379: unused variable 'kept_nums'
- src/autoreels/cloud/label.py:625: unused variable 'err2'
- src/autoreels/cloud/plan.py:313: unused function '_ends_with_stop'
- src/autoreels/cloud/plan.py:397: unused property 'aligned'
- src/autoreels/cloud/providers.py:340: unused variable 'last_status'
- src/autoreels/cloud/providers.py:372: unused variable 'last_status'
- src/autoreels/cloud/snap.py:123: unused function '_pause_word_ends'
- src/autoreels/cloud/snap.py:225: unused function '_prefer_longer_end'
- src/autoreels/core/calibration.py:56: unused class 'Calibrator'
- src/autoreels/core/env.py:20: unused variable 'API_KEY_NAMES'
- src/autoreels/core/models.py:169: unused variable 'self_contained_start'
- src/autoreels/core/models.py:170: unused variable 'start_justification'
- src/autoreels/core/models.py:203: unused variable 'subtitle_emph_words'
- src/autoreels/local/calibrate.py:312: unused method 'do_GET'
- src/autoreels/local/calibrate.py:318: unused method 'do_POST'
- src/autoreels/local/calibrate.py:334: unused method 'log_message'
- src/autoreels/local/render.py:132: unused variable 'wall'
- src/autoreels/prepare.py:20: unused variable 'STAGES'

## B. Config fields defined but never read (a YAML knob that does nothing?)

- src/autoreels/core/config.py:1062: unused method '_validate_transition'
- src/autoreels/core/config.py:1069: unused method '_validate_role'
- src/autoreels/core/config.py:489: unused variable 'chunk_overlap_sec'
- src/autoreels/core/config.py:553: unused variable 'prompt_language'
- src/autoreels/core/config.py:644: unused method '_sync_block_min_sec'
- src/autoreels/core/config.py:767: unused variable 'intrusion_guard_sec'
- src/autoreels/core/config.py:844: unused variable 'margin_v'
- src/autoreels/core/config.py:846: unused variable 'font_dir'
- src/autoreels/core/config.py:996: unused variable 'shot_tolerance_frames'

## C. Used only by tests (production never calls)

- src/autoreels/__main__.py:1676: unused function '_shot_spans_merged'
- src/autoreels/__main__.py:1889: unused function 'assign_shots'
- src/autoreels/__main__.py:33: unused import 'filter_min_clip_duration'
- src/autoreels/__main__.py:3747: unused attribute 'ends_on_host_turn'
- src/autoreels/__main__.py:7012: unused import '_make_merged_block'
- src/autoreels/__main__.py:75: unused import 'borrow_from_archive'
- src/autoreels/cloud/blocks.py:1150: unused function '_make_merged_block'
- src/autoreels/cloud/label.py:1375: unused variable 'dt'
- src/autoreels/cloud/montage.py:101: unused function 'is_montage_line'
- src/autoreels/cloud/plan.py:387: unused attribute 'rejected_alignment'
- src/autoreels/cloud/plan.py:389: unused attribute 'rejected_alignment'
- src/autoreels/cloud/providers.py:1327: unused class 'FallbackLLM'
- src/autoreels/cloud/select.py:227: unused function 'filter_min_clip_duration'
- src/autoreels/cloud/select.py:357: unused attribute 'start_repair_sec'
- src/autoreels/cloud/select.py:371: unused attribute 'start_repair_sec'
- src/autoreels/cloud/select.py:386: unused attribute 'start_repair_sec'
- src/autoreels/cloud/snap.py:541: unused attribute 'start_drift_sec'
- src/autoreels/cloud/snap.py:566: unused attribute 'end_drift_sec'
- src/autoreels/cloud/snap.py:576: unused attribute 'end_drift_sec'
- src/autoreels/cloud/speechmap.py:40: unused variable 'CUT_PAUSE_MIN_SEC'
- src/autoreels/cloud/transcribe.py:414: unused attribute 'last_marks'
- src/autoreels/cloud/transcribe.py:422: unused attribute 'last_marks'
- src/autoreels/cloud/trim.py:99: unused attribute 'start_drift_sec'
- src/autoreels/core/models.py:102: unused variable 'prompt_leak_removed'
- src/autoreels/core/models.py:158: unused variable 'topic'
- src/autoreels/core/models.py:176: unused variable 'end_drift_sec'
- src/autoreels/core/models.py:179: unused variable 'start_drift_sec'
- src/autoreels/core/models.py:181: unused variable 'start_repair_sec'
- src/autoreels/core/models.py:182: unused variable 'ends_on_host_turn'
- src/autoreels/core/models.py:32: unused variable 'awaiting_review'
- src/autoreels/core/models.py:33: unused variable 'approved'
- src/autoreels/core/state.py:34: unused function 'file_sha256_cached'
- src/autoreels/local/archive.py:36: unused function 'is_archived'
- src/autoreels/local/archive.py:47: unused function 'archive_input'
- src/autoreels/local/archive.py:67: unused function 'borrow_from_archive'
- src/autoreels/local/render.py:339: unused function 'estimate_size_mb'
- src/autoreels/local/render.py:3908: unused function 'render_cut'
- src/autoreels/local/render.py:427: unused variable 'cq'

## D. `except …: pass/continue` (silent swallow)

- src/autoreels/__main__.py:1807
- src/autoreels/__main__.py:4476
- src/autoreels/__main__.py:4648
- src/autoreels/__main__.py:5247
- src/autoreels/__main__.py:6006
- src/autoreels/__main__.py:6962
- src/autoreels/__main__.py:10352
- src/autoreels/local/render.py:687

## E. Sizes

-  13266 src/autoreels/__main__.py
-   4024 src/autoreels/local/render.py
-  17290 total
- skip/xfail markers in tests: 29

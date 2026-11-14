"""The step stream definition lives ONCE, in the runtime: backend/app/director_model/features.py (Head Start's
discipline: training imports the serving code, so both compute the same numbers). This module re-exports it.

Every feature (FEATS, F = len(FEATS)), grouped as in features.py:
  ev_*            the event of this step: hello, ui, playback_start/end, typed, words (Arc ear partial), turn_start /
                  eager / end / resumed, arc (audio metadata), emotion, lesson, poll (telemetry + new sim events)
  ui_*            the UI event: tap_place, tap_artifact, button, end_shift, lesson_answer, barge_in, kid_done,
                  mission_start, other;  src_voice: a typed turn that came from the voice path
  dt_prev, since_turn_start, since_speech (last guide/crew sentence end), since_nudge, since_play
                  log-scaled seconds, 1 = unknown
  mode_* / mission_on / role_set      session mode (mission, academy, cadet), a mission is running, a role is set
  floor_* / kid_open / play_guide / play_crew / n_pending / n_held     who holds the floor, what is playing, unplayed
                  say/play decisions, held proactive decisions
  nw, changed, revised, n_changed     the kid's words so far and how they changed vs the previous step (revisions)
  has_num, n_loads, lx_*              lexical cues on the heard words (mission NLU tables: task, vehicle, question, wh,
                  confirm, cancel, negation, conditional, more/less/little/all/half/off/on, shelter, Houston, end shift,
                  cold; define, name given, pronoun, correction, misconception, tour, sound, crew)
  echo_share      share of the words found in what is playing (echo vs barge-in)
  gaz_match / gaz_artifact            the gazetteer links a place / a piece of hardware in the words
  last_stop       the newest word is a stop word (the kid is mid-phrase)
  nlu_n / nlu_clarify / nlu_conf / nlu_<type>   the rule NLU's own reading of the words (evidence, not the answer)
  tag_*           Arc Tagger read-out at the turn end: available, question / command_request / statement /
                  device_directed acts, mentions, numbers, PII, hard PII, command_complete
  dd_avail, dd, cc_avail, cc          Arc audio metadata: device_directed, command_complete
  emo_*           kid emotion (neutral, happy, excited, frustrated, confused, scared, bored)
  st_avail, power, life, dose_frac, dose_rate, load_<x> (7), storm, storm_sev, in_sun, earth_vis, next_comm, shelter,
  rover_busy, alerts, day, over, pending_confirm, d_power / d_life / d_dose (deltas since the previous step),
  low_power_night, referent ("it" has a referent), last_place      mission telemetry / state
  sim_*           new sim events at this poll: solar_storm, storm_warning, comm_open, storm_end, dose_alert, low_power,
                  sunset, failure, mission_complete, other
  lesson_on, lesson_step, acc_<accept type>, ls_<status>           Academy lesson state
Tokens: hashed newest K=8 words (bag); the last W=16 words with [number word, load synonym, task word, stop word, in
what's playing, query word] for the span heads.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.director_model.features import *  # noqa: E402,F401,F403

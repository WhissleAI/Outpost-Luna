# Round 15 (2026-11-22): raw features + reply / slot heads. SHADOW ONLY, nothing routed

See director_model/RESULTS.md "Round 15" for the tables. Summary in gate.json.

- Reduced round: 2,400 train sessions / 225,049 steps; 4,644 real-ear decodes (ABI 2); embedder + tagger loaded.
- Class gate vs ship (r12 routed), 12,215 turns: no class passes. Ignore-only: hot +17 (0 extra wrong, fails
  cls_voice_echo_os by 1), echo +1, quiet +5 (+1 extra wrong).
- New heads: reply top-1 / top-3 52.1 % / 63.3 % (nearest-line baseline 5.5 % / 13.6 %); ent on named places 50.7 %;
  opt on named options 79.5 %; nav_arg kind 95.8 % (majority 81.9 %); style vs steering 88.3 % (r12 84.7 %).
- Shipped: weights_r15.* as a shadow-only file (logged, never consulted). DEFAULT_MODE and the r12 routed policy are
  unchanged.

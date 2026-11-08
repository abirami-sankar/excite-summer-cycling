# demo_voices

Pre-recorded human voice clips for the gaze study. Played by
`route_artifacts_poc/demo_audio_memories.py` as the rider passes each clip's spot
on the campus loop (1344 m).

## Naming = where it plays

Put the route position at the front of the file name:

| File name | Plays at | Author | Caption (terminal only) |
|---|---|---|---|
| `300m_alice_good-luck-on-finals.mp3` | 300 m | alice | good luck on finals |
| `620_bob.wav` | 620 m (no unit = metres) | bob | — |
| `1.05km_carol_almost-home.ogg` | 1050 m | carol | almost home |
| `welcome.mp3` (no position) | spaced evenly along the route | welcome | — |

- Formats: `.mp3`, `.wav`, `.ogg`.
- Positions past 1344 m are skipped (with a warning).
- Each clip starts ~30 m **before** its spot and fades out ~100 m after it. Two
  clips within that window play on top of each other.
- The folder is read fresh on every run, so you can rename, add or remove files
  without touching the code or the recordings store.

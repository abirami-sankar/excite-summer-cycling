# Training / source videos (not in git)

The large source ride videos live here **locally** but are **git-ignored** —
they exceed GitHub's 100 MB per-file limit (up to ~1.2 GB each). Nothing in the
LIVE experience needs them; only the offline tools do:

- `demo_experience.py` → needs `RouvyCampusTest.mp4`
- `stream_hud.py`, `live_readout.py`, `route_artifacts_poc/demo_artifacts_video.py`
  → any recorded ride video

Get them from the archived original project folder / shared drive and drop them
here. Expected files:

```
RouvyCampusTest.mp4
trimmed-video.mp4
RouvyScreen.mp4
Rouvy-BrooklineNorth.mp4
```

# Ping Pong VAR

Video Assistant Referee for table tennis: Android phone camera → OpenCV ball track → IN/OUT calls → **rules-aware match scoring** → VAR review → replay.

## Quick start

```powershell
cd C:\Users\janwaar\pingpong-var
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Open **http://127.0.0.1:8765** (or `http://PC_LAN_IP:8765` from another device on the same Wi‑Fi).

## Phone camera (Android)

1. Install **IP Webcam** → **Start server**.
2. Paste `http://PHONE_IP:8080/video` into **Phone camera** → **Connect phone**.
3. Phone and PC must be on the same Wi‑Fi.

## Match day flow

1. **Start match**: names, best-of 3/5/7, first server (or random).
2. Calibrate table corners TL → TR → BR → BL.
3. Award points live. Serve, ends, and games follow ITTF-style rules.
4. **Review** the latest point: uphold / overturn / void (replay clip when available).
5. **Undo** restores state by replaying the event history.
6. On match complete, read the summary; completed matches are saved under `data/matches/`.

## Scoring rules implemented

- Games to 11, win by 2
- Serve every 2 points; every point from 10–10
- Receiver of one game serves first in the next
- Ends switch after each game
- Deciding game: switch ends when either player first reaches 5
- Best-of-3 / 5 / 7 match formats
- Event-sourced state (reviews never delete original point events)

## Tests

```powershell
cd C:\Users\janwaar\pingpong-var
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "$PWD"
pytest tests/test_scoring.py -v
```

## Project layout

```
pingpong-var/
  main.py
  config.yaml
  src/
    camera.py / tracker.py / referee.py / replay.py / engine.py
    scoring/          # event models, reducer, match service, JSON persistence
    score.py          # thin legacy facade
    web/              # FastAPI UI
  tests/test_scoring.py
  data/matches/       # completed match JSON
  data/replays/       # mp4 clips
```

## Limits

- Bounce detection is heuristic (not a trained model).
- One camera; IN/OUT is a 2D table polygon test.
- Review currently targets the latest point only.
- White-ball HSV may need lighting tweaks.

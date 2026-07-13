# Ping Pong VAR

Video Assistant Referee for table tennis: Android phone camera → OpenCV ball track → IN/OUT calls → scoreboard → replay review.

## Quick start

```powershell
cd C:\Users\janwaar\pingpong-var
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Open **http://127.0.0.1:8765**

## Phone camera (Android)

1. Install **IP Webcam** from the Play Store.
2. Open the app → **Start server**.
3. Note the URL (e.g. `http://192.168.1.42:8080`).
4. On the same Wi‑Fi as your PC, paste `http://PHONE_IP:8080/video` into the **Phone camera** box in the UI (or edit `config.yaml`).
5. Click **Connect phone**.

For desk testing without a phone, the app falls back to your PC webcam (`camera_index: 0`).

## Match day flow

1. Point the phone at the full table (tripod helps).
2. Click the four table corners in order: **TL → TR → BR → BL**.
3. Tune **HSV** if the ball isn’t tracked (defaults target **white** balls; raise `V_lo` if lights confuse it, lower `S_hi` if skin/walls get picked up).
4. Play — auto IN/OUT fires on bounce heuristics; green table overlay shows the legal surface.
5. Use **Score** buttons for points (or award after an OUT).
6. Hit **Save last 8s challenge** or rely on auto-saved bounce clips under **Replay review**.

## Project layout

```
pingpong-var/
  main.py
  config.yaml
  src/
    camera.py      # phone MJPEG / webcam
    tracker.py     # HSV ball detect
    referee.py     # table polygon IN/OUT
    score.py       # 11-point games
    replay.py      # rolling buffer + mp4 clips
    engine.py      # live pipeline
    web/           # FastAPI UI
```

## Limits (MVP)

- Bounce detection is velocity-based, not a trained bounce model — expect some false positives/negatives.
- One camera, no stereo depth; “edge” calls are 2D polygon tests in the camera plane.
- White-ball tracking can confuse bright table lines / reflections — tighten HSV or improve lighting if needed.

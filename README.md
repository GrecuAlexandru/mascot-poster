# Automated Short-Form Video Platform

Creates vertical comparison videos for TikTok, YouTube Shorts, and Instagram Reels. It can plan a topic, research claims, write a script, generate narration and images, render the video, and publish it through the API.

## Run the application

Install the project dependencies once in a Python 3.12+ environment:

```powershell
python -m pip install -e ".[dev]"
```

Start the Streamlit dashboard:

```powershell
python -m streamlit run streamlit_app.py
```

Open the URL shown in the terminal, usually http://localhost:8501. The dashboard
is fully self-contained — it imports the rendering, topic, script, research,
fact-check, image, quality, publishing, and analytics services directly. No
separate FastAPI process is needed.

The entire pipeline is available as tabs in the dashboard:

1. **Topic** — create a comparison topic manually, generate candidates with AI,
   or load from a fixture.
2. **Research** — search and synthesize facts for the topic (requires search +
   LLM providers, or load from fixture).
3. **Script** — generate a narration script with scene plans (requires LLM, or
   load from fixture).
4. **Fact Check** — verify script claims against research.
5. **Images** — acquire, normalize, and build comparison canvases for left/right
   images.
6. **Render** — auto-build a render spec from the script's scene plan, edit
   scenes visually, preview frames, and render the final video with audio muxing.
7. **Quality** — validate the rendered video (resolution, fps, duration, codecs)
   and generate a low-res preview.
8. **Publish** — approve/reject the job, publish to TikTok/YouTube/Instagram, and
   record analytics snapshots.

The FastAPI server can still be used independently if you prefer headless/API
access:

```powershell
python -m uvicorn --app-dir src app.main:app --reload
```

API docs are at http://127.0.0.1:8000/docs.

## Configuration

Copy `.env.example` to `.env` if you want to enable external providers. The local renderer and included mascot assets work without API keys.

| Variable | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | Topic, script, and fact-check generation |
| `ELEVENLABS_API_KEY` | Narration generation |
| `SEARCH_API_KEY` | Web research |
| `MASCOT_SET` | Mascot set to use; defaults to `default` |

## Useful optional commands

```powershell
python -m pytest tests/ -v
python scripts/validate_assets.py
python scripts/render_sample.py
```

The active mascot files are in `assets/mascots/default`. Their names are validated against the pose names used by the application.

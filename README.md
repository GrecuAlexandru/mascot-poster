# Automated Short-Form Video Platform

Creates vertical comparison videos for TikTok, YouTube Shorts, and Instagram Reels. The primary interface is a one-click generator that researches a comparison, writes and verifies a conclusive script, selects semantically validated paired images, generates word-timed narration and direction, and renders a 1080×1920 reference-style video.

## Run the application

Install the project and development dependencies:

```powershell
python -m pip install -e ".[dev]"
```

Start the one-click Streamlit generator:

```powershell
python -m streamlit run streamlit_app.py
```

Open the URL shown in the terminal, usually http://localhost:8501. Choose optional advanced settings and press **Generate video**. The final result includes the video, poster, exact transcript, direction timeline, paired-image brief, complete image-attempt provenance, and quality report. Failed jobs resume from their last completed checkpoint.

The FastAPI server remains available for headless and integration use:

```powershell
python -m uvicorn --app-dir src app.main:app --reload
```

API documentation is available at http://127.0.0.1:8000/docs.

## Configuration

Copy `.env.example` to `.env` and provide the external-provider credentials used by the one-click workflow.

| Variable | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | Text models, semantic vision validation, and transparent image generation through OpenRouter |
| `OPENROUTER_IMAGE_MODEL` | Transparent image model; defaults to `openai/gpt-image-1-mini` |
| `OPENROUTER_VISION_MODEL` | Semantic image validator; defaults to `openai/gpt-4o-mini` |
| `ELEVENLABS_API_KEY` | Word-timed narration generation |
| `ELEVENLABS_VOICE_ID_RO` | Default Romanian narrator voice |
| `ELEVENLABS_VOICE_ID_EN` | Default English narrator voice |
| `SEARCH_API_KEY` | Web research and image search |
| `MASCOT_SET` | Mascot set; defaults to `default` |

## Validation and calibration

```powershell
python -m pytest tests/ -v
python scripts/validate_assets.py
python scripts/generate_mascot_calibration.py
python scripts/render_sample.py
python scripts/render_reference_acceptance.py
```

The active mascot files and editable `pose_calibration.json` are in `assets/mascots/default`. The calibration generator creates one 1080×1920 preview for every pose, a contact sheet, and an index in `output/mascot_calibration`. Every preview uses the fixed reference dot at `(540, 1670)`; the dot is never included in production video frames.

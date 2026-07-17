from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_weekly_prompt_has_manual_inputs_scoring_and_csv() -> None:
    text = (PROJECT_ROOT / "src/app/prompts/weekly_content_ideas.md").read_text(
        encoding="utf-8"
    )

    for marker in (
        "{candidate_count}",
        "{topic_history}",
        "{blacklist}",
        "visual_clarity",
        "image_acquisition_difficulty",
        "factual_risk",
        "Second-pass critique",
        "```csv",
        "```json",
        '"ideas"',
        '"idea_id"',
        '"left"',
        '"right"',
        '"angle"',
        "ideas_json",
        "Do not edit files",
    ):
        assert marker in text


def test_weekly_prompt_requires_romanian_and_marks_ideas_unverified() -> None:
    text = (PROJECT_ROOT / "src/app/prompts/weekly_content_ideas.md").read_text(
        encoding="utf-8"
    )

    assert "Romanian" in text
    assert "unverified" in text.lower()
    assert "two concrete physical objects" in text.lower()

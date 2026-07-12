# Compact Adaptive Captions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render short caption groups as compact one- or two-row subtitles that match the reference video’s reading rhythm.

**Architecture:** `TimelineCompiler` continues to make four-word caption groups. `ReferenceRenderer` measures the words at the chosen font size and partitions them into one or two ordered rows, keeping long phrases balanced and centered. Existing per-word highlighting uses the original word index and therefore follows the selected row automatically.

**Tech Stack:** Python 3.14, Pillow, pytest.

## Global Constraints

- Caption groups contain no more than four words.
- Captions have at most two rows and preserve spoken-word order.
- One- and compact two-word captions use one row; three- and four-word captions use balanced two-row layouts.
- A very long word remains in a centered row and existing font fitting keeps it inside the caption region.
- Use type hints and add no source comments.

---

### Task 1: Add compact caption row partitioning

**Files:**
- Modify: `C:/Users/Alex/Desktop/mascot-poster/src/app/rendering/reference_renderer.py:198-228`
- Modify: `C:/Users/Alex/Desktop/mascot-poster/tests/unit/test_reference_renderer.py`

**Interfaces:**
- Consumes: `ReferenceRenderer._caption_layout(words: list[str], region: Region)`.
- Produces: `ReferenceRenderer._caption_layout(words: list[str], region: Region) -> tuple[ImageFont.FreeTypeFont, list[list[str]]]`, with one or two ordered rows.

- [ ] **Step 1: Write the failing tests**

```python
def _caption_renderer(tmp_path: Path) -> ReferenceRenderer:
    mascot_dir = tmp_path / "mascot"
    _make_mascot_assets(mascot_dir)
    return ReferenceRenderer(
        templates_dir=Path(__file__).resolve().parents[2] / "templates",
        mascots_dir=mascot_dir,
    )


def test_reference_caption_layout_keeps_compact_groups_on_one_row(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)
    _, one_word_lines = renderer._caption_layout(["Natural"], renderer.template.region("caption"))
    _, lines = renderer._caption_layout(["Aroma", "pură"], renderer.template.region("caption"))
    assert one_word_lines == [["Natural"]]
    assert lines == [["Aroma", "pură"]]


def test_reference_caption_layout_balances_longer_groups_over_two_rows(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)
    _, lines = renderer._caption_layout(
        ["Avem", "zahăr", "vanilat", "natural"],
        renderer.template.region("caption"),
    )
    assert lines == [["Avem", "zahăr"], ["vanilat", "natural"]]


def test_reference_caption_layout_splits_three_words_over_two_rows(tmp_path: Path) -> None:
    renderer = _caption_renderer(tmp_path)
    _, lines = renderer._caption_layout(
        ["Are", "aromă", "naturală"],
        renderer.template.region("caption"),
    )
    assert lines == [["Are", "aromă"], ["naturală"]]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_reference_renderer.py -k "caption_layout" -v`

Expected: FAIL because the existing width-only layout returns a single row for the four-word group.

- [ ] **Step 3: Implement the minimal partitioning rule**

```python
    def _caption_layout(self, words: list[str], region: Region):
        size = self.template.fonts["caption"].size
        while True:
            font = load_font(self.font_path, size)
            lines = self._caption_lines(words, font, min(region.width, 720))
            fits_width = all(
                sum(measure_text(word, font)[0] for word in line)
                + round(size * 0.28) * (len(line) - 1) <= region.width
                for line in lines
            )
            if (fits_width and round(size * 1.22) * len(lines) <= region.height) or size <= 56:
                return font, lines
            size -= 7

    def _caption_lines(self, words: list[str], font, compact_width: int) -> list[list[str]]:
        if len(words) <= 1:
            return [words]
        if len(words) == 2:
            gap = round(font.size * 0.28)
            width = sum(measure_text(word, font)[0] for word in words) + gap
            return [words] if width <= compact_width else [[words[0]], [words[1]]]
        return [words[:2], words[2:]]
```

Use a compact threshold of 720 pixels. Three-word captions use a two-plus-one split and four-word captions use a two-plus-two split. The fit loop must keep the existing font reduction so unusually long words remain within the caption region.

- [ ] **Step 4: Run the focused renderer tests**

Run: `python -m pytest tests/unit/test_reference_renderer.py -k "caption_layout or reference_renderer" -v`

Expected: PASS with the compact two-word group on one row and the four-word group in two balanced rows.

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest tests/ -v`

Expected: PASS with no regressions.

- [ ] **Step 6: Commit the implementation**

```bash
git add src/app/rendering/reference_renderer.py tests/unit/test_reference_renderer.py
git commit -m "compact reference captions"
```

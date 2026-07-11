# Step 2 — Phase 2: TTS Integration

> Goal of this step: generate narration audio from plain text and use it in the
> renderer built in Phase 1. Produce word/sentence timing so subtitles and scene
> pacing can sync to real speech.

Sections in this step:

- [Phase 2 milestone](#phase-2-tts-integration)
- [16. Text-to-Speech](#16-text-to-speech)
- [17. Timing and Alignment](#17-timing-and-alignment)
- [20. Audio Mixing](#20-audio-mixing)

---

## Phase 2: TTS integration

Add:

- ElevenLabs provider
- Romanian and English voice configuration
- Audio caching
- Duration extraction
- Retry logic
- Cost tracking

Deliverable:

- Generate narration from plain text
- Render video using generated narration

---

## 16. Text-to-Speech

Recommended production provider: ElevenLabs.

Support at least:

- Romanian voice
- English voice
- Voice style instructions
- Voice ID per channel
- Adjustable stability
- Adjustable similarity
- Adjustable style exaggeration
- Speed control
- Retry generation
- Audio caching

### TTS interface

```python
class TTSProvider(Protocol):
    async def synthesize(
        self,
        text: str,
        voice_id: str,
        language: str,
        output_path: Path,
        settings: TTSSettings,
    ) -> TTSResult:
        ...
```

### TTS result

```python
class TTSResult(BaseModel):
    path: str
    duration_seconds: float
    provider: str
    model: str
    character_count: int
    estimated_cost_usd: float
```

### Performance style

For a mascot-style voice, the instructions should ask for:

- Cheerful delivery
- Youthful energy
- Slightly exaggerated emphasis
- Clear pronunciation
- Quick but understandable pacing
- Short dramatic pauses
- Not too childish
- Not like an advertisement
- Consistent personality across episodes

### Retry rules

Retry when:

- Audio file is invalid
- Duration is outside expected range
- Silence is detected
- Speech is clipped
- Pronunciation is unusable
- Provider returns a transient error

Do not retry more than the configured limit.

Save every attempt for debugging, but only retain the final accepted version long-term.

---

## 17. Timing and Alignment

The system knows the exact narration text, so timing can be generated reliably.

### Preferred method

Use one of:

- Provider-supplied timestamps
- Forced alignment
- Word-level speech recognition
- Sentence-level proportional timing as fallback

### Required output

```python
class TimedWord(BaseModel):
    word: str
    start: float
    end: float
```

```python
class TimedPhrase(BaseModel):
    text: str
    start: float
    end: float
```

The subtitle service selects important phrases from the script and maps them to timestamps.

The example style does not need full karaoke subtitles. It can show:

- One word
- Two to five-word phrase
- Important number
- Key difference
- Final verdict

---

## 20. Audio Mixing

The audio service should combine:

- Narration
- Background music
- Sound effects

### Recommended levels

- Narration: primary
- Music: approximately -24 to -18 LUFS relative feel
- Effects: noticeable but below speech
- Apply ducking when narration is present
- Normalize final output
- Prevent clipping

FFmpeg filters can handle:

- `loudnorm`
- `amix`
- `volume`
- `sidechaincompress`
- fades
- trimming

Background music should be licensed and reusable.

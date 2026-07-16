# Buffer Highlighted Thumbnail Design

## Goal

Make Buffer select the actual video frame where Pufăilă says „Dar care e diferența?”, specifically while the karaoke caption highlights the word „diferența”.

## Design

The final timed transcript is the source of truth for both caption highlighting and thumbnail timing. After narration timing is complete, the renderer normalizes transcript words by lowercasing, removing punctuation, and folding Romanian diacritics for matching only. It searches for the consecutive phrase `dar care e diferenta`.

When the phrase is found, the thumbnail timestamp is the midpoint between the spoken word’s `start` and `end` times for „diferența”. The caption renderer uses the same timing interval, so the selected MP4 frame contains the highlighted word rather than merely the surrounding sentence.

The renderer writes the selected offset in milliseconds to a non-secret `thumbnail.json` artifact beside the final MP4. The publication service reads that metadata only after the exact MP4 has been approved and passes the offset to Buffer as the video asset’s `thumbnailOffset`. The dedicated designed thumbnail image remains an internal artifact and is not inserted into the video or uploaded in place of an actual frame.

## Fallback and safety

If the exact phrase is absent, timing metadata is malformed, or the file is missing, publishing uses the configured fallback offset, currently 2000 milliseconds. A bad or negative value is never sent to Buffer.

Thumbnail selection does not weaken the existing controls: Buffer receives media only after Telegram approval, the approved MP4 hash must still match, and retries remain idempotent.

## Existing videos

Videos rendered before this feature do not contain `thumbnail.json`. They retain the fallback offset unless rerendered. Regenerating images, script, or the full video produces fresh thumbnail metadata as part of the render artifacts.

## Verification

Automated coverage must prove:

- Romanian punctuation and diacritics still match the target phrase.
- The selected time is inside the „diferența” word interval, at its midpoint.
- Render output writes the same offset to `thumbnail.json` and the typed render result.
- Publication passes that exact offset to Buffer.
- Missing, malformed, or negative metadata falls back safely.
- The normal video has no injected thumbnail tail or artificial freeze frame.

Production acceptance extracts the frame at the generated offset from a real MP4 and visually confirms that the displayed caption highlights „diferența” before any Buffer submission is tested.

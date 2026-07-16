# Single-Line CTA Banner Design

## Goal

Keep the closing `LIKE · SHARE · FOLLOW` banner on one centered line in every 1080×1920 Mascot Poster video.

## Design

The CTA keeps its current wording, safe horizontal region, colors, font family, rounded card, and placement relative to Pufăilă. The renderer treats the complete display text as one indivisible line and measures it against the card's available inner width.

If the text does not fit at the preferred CTA font size, the renderer reduces the font size until the complete line fits. It must never wrap or split the three actions across rows. The card height is calculated from the resulting single line plus the existing vertical padding, so no empty second-row space remains.

The renderer continues to use `LIKE · SHARE · FOLLOW` as the normalized display text when the generation pipeline supplies `Like, share, follow`.

## Constraints

- Keep the exact visible text `LIKE · SHARE · FOLLOW`.
- Keep all text inside the existing safe horizontal bounds.
- Keep the banner centered and readable.
- Do not widen it beyond the video-safe region.
- Do not change CTA timing, animation, colors, or publication behavior.
- Do not affect normal karaoke captions or thumbnail rendering.

## Verification

Automated renderer coverage must assert that CTA line calculation returns exactly one line for the production text and that its measured width fits the available inner width. A rendered closing frame must be inspected at 1080×1920 to confirm the banner is visually centered, fully contained, and uses one row.

The current review candidate may be rerendered from existing checkpoints after deployment so this layout can be verified without repeating topic, research, image, script, or TTS generation.

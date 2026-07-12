# Active Caption and Dialogue Style Design

## Goal

Match the supplied reference more closely by simplifying progressive caption highlighting, keeping comparison objects visually balanced, and making Romanian narration sound conversational, modern, and concise.

## Captions

- Keep every word in the current one-to-four-word caption phrase visible.
- Draw a rounded background only behind the active spoken word.
- Use the same coral background, `#E87560`, for every active word.
- Keep active text yellow and inactive text white, both with the existing dark outline and shadow.
- Preserve the existing compact one- or two-row caption layout.

## Product sizing

- Trim transparent padding before sizing either product.
- Give both products the same neutral maximum visible extent and center each in its half of the frame.
- Preserve the existing 128% focus zoom. Equality applies to neutral base sizing; the active product may temporarily grow when discussed.

## Romanian dialogue style

- Prompt for speech that sounds like a modern person talking to a friend, not a formal educator or article.
- Allow light irony, contemporary vocabulary, and a playful comparison when it remains natural and factually supported.
- Avoid forced slang, exaggerated jokes, advertising language, and invented facts.
- Include the supplied vanilla-sugar transcript as a style example, while explicitly treating its factual content as an example rather than reusable evidence.
- Require the final explanatory beat to begin with `Pe scurt,` and contain one genuinely short verdict of 4-12 words after the prefix.
- Keep the Pufăilă sign-off as a separate closing beat.
- Apply the same structural rule in English with `In short,`.

## Testing

- Verify only the active caption word receives the fixed coral background.
- Verify inactive caption words have no background.
- Verify neutral product extents remain equal and the active-side zoom remains 128%.
- Verify the generated script prompt contains the conversational style, transcript example, factual-use warning, and short-conclusion constraint.


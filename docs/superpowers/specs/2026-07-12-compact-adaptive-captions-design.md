# Compact Adaptive Captions Design

## Goal

Match the reference video’s compact subtitle rhythm: captions contain no more than four spoken words and use at most two centered rows. Long lines must not force viewers to scan across most of the screen.

## Caption grouping

The timeline compiler continues to create groups of no more than four words. Existing punctuation, timing-gap, and character-limit boundaries remain in effect.

## Layout rules

- One-word captions use one centered row.
- Two-word captions use one centered row when their rendered width is within the compact line-width threshold; otherwise they use one word per row.
- Three- and four-word captions use two rows, balanced as two-plus-one and two-plus-two words respectively.
- A row may contain fewer words when a long word would exceed the compact line-width threshold.
- Captions never use more than two rows.

The renderer owns the layout decision because it has the font metrics needed to measure the actual rendered words. It returns rows of original word order, then draws and highlights each word in the row containing it.

## Error handling

If an exceptionally long single word exceeds the compact threshold, it remains on its own centered row and the existing font-size reduction keeps it inside the caption region.

## Tests

Add renderer tests for one, two, three, and four word groups. Verify their row counts and word distribution. Retain timeline tests to verify the four-word maximum and spoken-word highlighting behavior.

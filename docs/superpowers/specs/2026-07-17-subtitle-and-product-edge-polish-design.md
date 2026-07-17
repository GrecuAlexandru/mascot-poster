# Subtitle and Product Edge Polish Design

## Goal

Improve the reference video renderer in two focused ways:

- Make captions feel clean and intentional while retaining the existing coral, mustard, and mint palette.
- Remove visible rectangular borders around product images whose source backgrounds are white or nearly white.

The work is limited to deterministic rendering and product asset normalization. It does not change provider interfaces, domain schemas, API contracts, or generation prompts.

## Observed Problems

### Captions

The current caption renderer creates a different irregular polygon and slight rotation for every word. The combined variation makes a short phrase look uneven rather than deliberately designed. The active word only grows by six percent and moves up six pixels, so the spoken-word state is difficult to distinguish at playback speed.

### Product images

The normalizer finds the non-white subject bounds and crops to them, but it retains all pixels inside that crop as opaque. A white or slightly tinted source background therefore remains a rectangle around the product. Resizing with Lanczos makes the remaining background and its edge pixels visible against the renderer's pure-white canvas.

## Approved Visual Direction

### Editorial caption tiles

Every visible word receives a tidy, softly rounded tile. Tiles use the existing coral, mustard, and mint sequence with dark text. They sit on a stable baseline with consistent spacing and no per-word rotation or randomized corners.

The currently spoken word receives all of the following cues:

- Six to eight percent scale increase.
- Small vertical lift.
- Dark two- or three-pixel keyline.
- Stronger but compact shadow.

Caption layout reserves the maximum active-word extent before positioning the phrase. Changing the active word must not make the phrase jump or reflow between frames.

### Border-connected background removal

Product normalization estimates the light background color from perimeter pixels. It identifies only background-like pixels that are connected to the image boundary and converts that connected area to transparency. White regions enclosed inside the product remain opaque.

The resulting subject receives a small transparent safety margin before it is cached or resized. The margin prevents the visible subject from touching the crop boundary and avoids introducing a new hard edge during interpolation.

## Architecture and Data Flow

### Caption rendering

`ReferenceRenderer` keeps responsibility for caption layout and raster composition.

1. The existing `CaptionCue` supplies the visible words and active word index.
2. Layout calculates every word tile using the active-state maximum extent.
3. The phrase is split into one or two rows using those reserved extents.
4. Inactive tiles are rendered with the selected palette color, dark text, and compact shadow.
5. The active tile adds the keyline, stronger shadow, lift, and scale without changing neighboring positions.
6. The composed caption remains within the template caption region.

The caption cue model and timing behavior remain unchanged.

### Product normalization

`ProductAssetNormalizer` remains the single source of visible-subject normalization.

1. Convert the source to RGBA.
2. Prefer a meaningful existing alpha channel when one is present.
3. For opaque images, estimate a near-white background from edge pixels.
4. Build a candidate background mask using color distance from the estimated background.
5. Retain only candidate pixels connected to the image boundary.
6. Convert the connected background to transparency and soften the immediate fringe deterministically.
7. Calculate visible bounds from the cleaned alpha channel.
8. Apply the existing occupancy validation to the detected subject.
9. Crop to the visible bounds and add a small transparent margin.
10. Save or cache the normalized RGBA result for paired sizing and rendering.

The renderer continues to use normalized visible bounds and equal apparent product height.

## Safety and Error Handling

- Background removal is limited to light, low-saturation, edge-connected pixels. It must not globally remove white pixels.
- If the perimeter does not provide a sufficiently consistent light background, normalization preserves the existing pixels and follows the current visible-mask behavior.
- A fully blank image continues to fail with a clear validation error.
- Existing minimum subject-occupancy validation remains in force.
- Transparent input images continue to use their alpha channel and are not unnecessarily re-keyed.
- Normalization remains deterministic and does not introduce provider calls or nondeterministic thresholds.

## Testing Strategy

Caption tests will verify:

- Tile geometry is stable and softly rounded.
- No caption tile rotation or randomized corner geometry remains.
- Palette colors and dark text are preserved.
- The active word has a visible keyline, scale increase, lift, and stronger shadow.
- Changing the active word does not change phrase bounds or neighboring tile positions.
- Long Romanian words remain inside the configured caption region.

Product normalization tests will verify:

- Pure-white and off-white edge-connected backgrounds become transparent.
- Enclosed white details inside a colored subject remain opaque.
- Soft source shadows do not create a rectangular crop boundary.
- Existing transparent inputs remain correct.
- Minimum occupancy rejection still works.
- Resized normalized products do not introduce non-white rectangular seams on the white render canvas.

Focused tests will be written and observed failing before production changes. After implementation, the focused renderer and normalizer tests will run first, followed by the complete unit test suite and a fresh acceptance render for visual inspection.

## Acceptance Criteria

- Captions use clean editorial tiles with no jagged corners or rotations.
- The spoken word is immediately recognizable without causing layout jitter.
- Existing caption colors, word alignment, and timing remain intact.
- White or near-white product source backgrounds do not produce visible rectangular borders.
- White product details are preserved.
- Product sizing, paired alignment, staged reveals, and focus animations continue to work.
- All relevant automated tests and the full unit test suite pass.

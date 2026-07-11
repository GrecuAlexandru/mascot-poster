# Step 5 — Phase 5: Image Generation

> Goal of this step: generate or acquire the two comparison images automatically,
> normalize them to the comparison canvas, and cache them.

Sections in this step:

- [Phase 5 milestone](#phase-5-image-generation)
- [15. Image Generation and Processing](#15-image-generation-and-processing)

---

## Phase 5: Image generation

Add:

- Cloud image provider
- Prompt templates
- Image normalization
- Caching
- Asset validation

Deliverable:

- Two comparison images generated automatically

---

## 15. Image Generation and Processing

The image service should support multiple providers.

### Mode A: Cloud image generation

Generate one image for each comparison item.

Prompt requirements:

- Centered subject
- Clean background
- No text
- No watermark
- Similar camera angle between both images
- Consistent lighting
- High contrast
- Easy to crop
- No unnecessary objects

### Mode B: Remote product images

Use images from approved sources.

The pipeline must:

- Download the image
- Verify MIME type
- Verify dimensions
- Detect corruption
- Remove metadata
- Resize safely
- Add padding if needed
- Optionally remove background
- Save normalized PNG or WebP

### Normalization output

```text
1080×700 comparison canvas
left object centered in left region
right object centered in right region
equal visual scale
consistent shadow
consistent margin
```

### Caching

Hash prompts and URLs.

Do not regenerate or redownload identical assets unnecessarily.

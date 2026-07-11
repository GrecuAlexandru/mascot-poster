from pathlib import Path

from PIL import Image


POSES = (
    "neutral",
    "intro_hands_up",
    "present_both",
    "point_left",
    "point_right",
    "point_up",
    "point_down",
    "point_up_left",
    "point_up_right",
    "two_fingers_up",
    "idea",
    "thinking",
    "surprised",
    "explaining",
    "compare_left_right",
    "thumbs_up",
    "warning",
    "shrug",
    "celebrate",
    "outro_wave",
    "magnifying_glass",
    "reading_note",
    "phone_in_hand",
    "arms_crossed",
)


CANVAS_SIZE = (640, 640)
HEAD_ANCHOR = (320, 265)


def largest_component_bounds(mask: Image.Image) -> tuple[int, int, int, int] | None:
    width, height = mask.size
    pixels = mask.load()
    visited = bytearray(width * height)
    largest_area = 0
    largest_bounds: tuple[int, int, int, int] | None = None

    for y in range(height):
        for x in range(width):
            index = y * width + x
            if visited[index] or pixels[x, y] == 0:
                continue
            stack = [(x, y)]
            visited[index] = 1
            area = 0
            left = right = x
            top = bottom = y
            while stack:
                current_x, current_y = stack.pop()
                area += 1
                left = min(left, current_x)
                right = max(right, current_x)
                top = min(top, current_y)
                bottom = max(bottom, current_y)
                for offset_x, offset_y in (
                    (-1, -1),
                    (0, -1),
                    (1, -1),
                    (-1, 0),
                    (1, 0),
                    (-1, 1),
                    (0, 1),
                    (1, 1),
                ):
                    neighbor_x = current_x + offset_x
                    neighbor_y = current_y + offset_y
                    neighbor_index = neighbor_y * width + neighbor_x
                    if (
                        0 <= neighbor_x < width
                        and 0 <= neighbor_y < height
                        and not visited[neighbor_index]
                        and pixels[neighbor_x, neighbor_y] != 0
                    ):
                        visited[neighbor_index] = 1
                        stack.append((neighbor_x, neighbor_y))
            if area > largest_area:
                largest_area = area
                largest_bounds = (left, top, right + 1, bottom + 1)

    return largest_bounds


def crop_content(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    mask = Image.new("L", image.size)
    mask.putdata(
        [255 if min(pixel) < 235 else 0 for pixel in rgb.get_flattened_data()]
    )
    largest_bounds = largest_component_bounds(mask)
    if largest_bounds is None:
        raise ValueError("The crop tile contains no visible mascot content.")
    left, top, right, bottom = largest_bounds
    padding = 8
    return image.crop(
        (
            max(0, left - padding),
            max(0, top - padding),
            min(image.width, right + padding),
            min(image.height, bottom + padding),
        )
    )


def align_pose(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    head_mask = Image.new("L", image.size)
    head_mask.putdata(
        [
            255
            if red >= 180 and 70 <= green <= 205 and blue <= 120 and red - blue >= 100
            else 0
            for red, green, blue in rgb.get_flattened_data()
        ]
    )
    head_bounds = largest_component_bounds(head_mask)
    if head_bounds is None:
        raise ValueError("The pose does not contain a detectable mascot head.")
    left, top, right, bottom = head_bounds
    head_center = ((left + right) // 2, (top + bottom) // 2)
    canvas = Image.new("RGB", CANVAS_SIZE, (255, 255, 255))
    offset = (HEAD_ANCHOR[0] - head_center[0], HEAD_ANCHOR[1] - head_center[1])
    if image.mode == "RGBA":
        canvas.paste(image, offset, image)
    else:
        canvas.paste(image.convert("RGB"), offset)
    return canvas


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    source_files = (root / "1.png", root / "2.png", root / "3.png")
    output_dir = root / "assets" / "mascot_poses"
    aligned_output_dir = root / "assets" / "mascot_poses_aligned"
    output_dir.mkdir(parents=True, exist_ok=True)
    aligned_output_dir.mkdir(parents=True, exist_ok=True)
    pose_index = 0

    for source_file in source_files:
        with Image.open(source_file) as sheet:
            tile_width = sheet.width // 3
            rows = 3 if source_file.name != "3.png" else 2
            tile_height = sheet.height // rows
            for row in range(rows):
                for column in range(3):
                    tile = sheet.crop(
                        (
                            column * tile_width,
                            row * tile_height,
                            (column + 1) * tile_width,
                            (row + 1) * tile_height,
                        )
                    )
                    pose = crop_content(tile)
                    output_file = output_dir / f"{POSES[pose_index]}.png"
                    pose.save(output_file, format="PNG")
                    align_pose(pose).save(
                        aligned_output_dir / f"{POSES[pose_index]}.png", format="PNG"
                    )
                    pose_index += 1

    if pose_index != len(POSES):
        raise RuntimeError(f"Expected {len(POSES)} poses, cropped {pose_index}.")


if __name__ == "__main__":
    main()

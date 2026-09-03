"""Remove the Gemini sparkle watermark from an image."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def get_ffmpeg_binary() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    return None


ALPHA_THRESHOLD = 0.002
MAX_ALPHA = 0.99
LOGO_VALUE = 255.0


def watermark_info(width: int, height: int) -> dict[str, int]:
    min_dimension = min(width, height)
    ratio = min_dimension / 1536
    size = max(16, round(96 * ratio))
    margin = max(8, round(64 * ratio))
    return {
        "size": size,
        "x": max(0, width - margin - size),
        "y": max(0, height - margin - size),
        "width": size,
        "height": size,
    }


def resolve_box(
    base: dict[str, int],
    width: int,
    height: int,
    size_scale: float = 1.0,
    offset_x: int = 0,
    offset_y: int = 0,
) -> dict[str, int]:
    size = max(8, min(round(base["size"] * size_scale), width, height))
    return {
        "size": size,
        "x": max(0, min(base["x"] + offset_x, width - size)),
        "y": max(0, min(base["y"] + offset_y, height - size)),
        "width": size,
        "height": size,
    }


def alpha_map(mask: Image.Image, size: int, gain: float) -> list[float]:
    resized = mask.resize((size, size), Image.Resampling.BICUBIC).convert("RGB")
    return [min(max(pixel) / 255.0 * gain, MAX_ALPHA) for pixel in resized.getdata()]


def get_image_layout_candidates(width: int, height: int) -> list[dict]:
    """Candidate layout families from main.js lines 674-723."""
    min_dim = min(width, height)
    base_ratio = min_dim / 1536.0
    base_size = max(16, round(96 * base_ratio))

    return [
        {
            "presetKey": "new",
            "name": "New Gemini (Adaptive)",
            "baseSize": base_size,
            "calcPos": lambda s: (
                max(0, width - max(8, round(192 * base_ratio)) - s),
                max(0, height - max(8, round(192 * base_ratio)) - s),
            ),
            "gain": 0.6,
            "prior": 1.08,
        },
        {
            "presetKey": "classic",
            "name": "Classic Corner (Adaptive)",
            "baseSize": base_size,
            "calcPos": lambda s: (
                max(0, width - max(8, round(64 * base_ratio)) - s),
                max(0, height - max(8, round(64 * base_ratio)) - s),
            ),
            "gain": 1.0,
            "prior": 1.04,
        },
        {
            "presetKey": "new",
            "name": "Gemini (Fixed 96px Inset)",
            "baseSize": 96,
            "calcPos": lambda s: (
                max(0, width - (192 if min_dim >= 1400 else round(128 * max(0.5, min_dim / 1024.0))) - s),
                max(0, height - (192 if min_dim >= 1400 else round(128 * max(0.5, min_dim / 1024.0))) - s),
            ),
            "gain": 0.6,
            "prior": 1.02,
        },
        {
            "presetKey": "classic",
            "name": "Classic Corner (Fixed 96px)",
            "baseSize": 96,
            "calcPos": lambda s: (
                max(0, width - (64 if min_dim >= 1024 else 32) - s),
                max(0, height - (64 if min_dim >= 1024 else 32) - s),
            ),
            "gain": 1.0,
            "prior": 1.01,
        },
    ]


def detect_watermark_box(
    image: Image.Image | np.ndarray,
    mask_image: Image.Image | None = None,
    base: dict[str, int] | None = None,
) -> dict[str, int]:
    """Find the exact location and scale of the watermark using candidate layout search and multi-scale template matching."""
    if isinstance(image, Image.Image):
        gray = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    else:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape

    assets_dir = Path(__file__).parent / "assets"
    m96 = Image.open(assets_dir / "bg_96.png")
    m48 = Image.open(assets_dir / "bg_48.png")
    m96_gray = np.array(m96.convert("L"))
    m48_gray = np.array(m48.convert("L"))

    layout_families = get_image_layout_candidates(width, height)
    scale_pyramid = (0.55, 0.70, 0.85, 1.00, 1.15, 1.30, 1.50, 1.70)

    best_match = None
    best_score = -1.0

    # 1. Test candidate layout families from main.js
    for layout in layout_families:
        for scale in scale_pyramid:
            s = max(16, min(round(layout["baseSize"] * scale), min(width, height) - 8))
            x, y = layout["calcPos"](s)
            if x < 0 or y < 0 or x + s > width or y + s > height:
                continue
            patch = gray[y : y + s, x : x + s]
            tpl = cv2.resize(m48_gray if s <= 48 else m96_gray, (s, s), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(patch, tpl, cv2.TM_CCOEFF_NORMED)
            weighted = float(res[0, 0]) * layout["prior"]
            if weighted > best_score:
                best_score = weighted
                best_match = {
                    "x": x,
                    "y": y,
                    "size": s,
                    "width": s,
                    "height": s,
                    "score": weighted,
                    "preset": layout["presetKey"],
                    "gain": layout["gain"],
                }

    # 2. Fine-tuning (±16px position, ±10% scale) from main.js line 753
    if best_match and best_match["score"] > 0.10:
        fine_sizes = {
            max(16, round(best_match["size"] * 0.90)),
            max(16, round(best_match["size"] * 0.95)),
            best_match["size"],
            min(min(width, height) - 8, round(best_match["size"] * 1.05)),
            min(min(width, height) - 8, round(best_match["size"] * 1.10)),
        }
        refined_x = best_match["x"]
        refined_y = best_match["y"]
        refined_s = best_match["size"]
        refined_score = best_match["score"]

        for ts in fine_sizes:
            tpl = cv2.resize(m48_gray if ts <= 48 else m96_gray, (ts, ts), interpolation=cv2.INTER_AREA)
            win_y0 = max(0, best_match["y"] - 16)
            win_y1 = min(height, best_match["y"] + 16 + ts)
            win_x0 = max(0, best_match["x"] - 16)
            win_x1 = min(width, best_match["x"] + 16 + ts)
            if win_y1 - win_y0 >= ts and win_x1 - win_x0 >= ts:
                sub_patch = gray[win_y0:win_y1, win_x0:win_x1]
                res = cv2.matchTemplate(sub_patch, tpl, cv2.TM_CCOEFF_NORMED)
                _, max_v, _, max_l = cv2.minMaxLoc(res)
                if max_v > refined_score:
                    refined_score = float(max_v)
                    refined_x = win_x0 + max_l[0]
                    refined_y = win_y0 + max_l[1]
                    refined_s = ts

        best_match["x"] = refined_x
        best_match["y"] = refined_y
        best_match["size"] = refined_s
        best_match["width"] = refined_s
        best_match["height"] = refined_s
        best_match["score"] = refined_score

    # 3. If layout candidates had low confidence, search the broader lower-right quadrant (for cropped images)
    if best_score < 0.45:
        roi = gray[int(height * 0.5) :, int(width * 0.5) :]
        rx0, ry0 = int(width * 0.5), int(height * 0.5)
        for mask_tpl, bsz in ((m48_gray, 48), (m96_gray, 96)):
            for sc in (0.5, 0.75, 1.0, 1.25):
                sz = int(round(bsz * sc))
                if sz < 16 or sz >= roi.shape[0] - 2 or sz >= roi.shape[1] - 2:
                    continue
                tpl = cv2.resize(mask_tpl, (sz, sz), interpolation=cv2.INTER_AREA)
                res = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
                _, mv, _, ml = cv2.minMaxLoc(res)
                if mv > best_score:
                    best_score = float(mv)
                    best_match = {
                        "x": rx0 + ml[0],
                        "y": ry0 + ml[1],
                        "size": sz,
                        "width": sz,
                        "height": sz,
                        "score": float(mv),
                        "preset": "custom",
                        "gain": 0.6,
                    }

    if best_match and best_match["score"] >= 0.35:
        return best_match

    # Fallback to New Gemini Adaptive (main.js line 805)
    fallback = layout_families[0]
    s = fallback["baseSize"]
    x, y = fallback["calcPos"](s)
    return {
        "x": x,
        "y": y,
        "size": s,
        "width": s,
        "height": s,
        "score": 0.0,
        "preset": "new",
        "gain": fallback["gain"],
    }


def detect_video_box(
    frame: np.ndarray,
    base: dict[str, int],
    mask_image: Image.Image,
) -> dict[str, int]:
    return detect_watermark_box(frame, mask_image, base)


def remove_watermark(
    image: Image.Image,
    mask: Image.Image | None = None,
    gain: float = 0.6,
    size_scale: float = 1.0,
    offset_x: int = 0,
    offset_y: int = 0,
    method: str = "reconstruct",
    box: dict[str, int] | None = None,
) -> Image.Image:
    width, height = image.size

    if mask is None:
        mask_path = Path(__file__).parent / "assets" / "bg_96.png"
        mask = Image.open(mask_path)

    if box is None:
        detected = detect_watermark_box(image, mask)
        box = resolve_box(detected, width, height, size_scale, offset_x, offset_y)
    else:
        box = resolve_box(box, width, height, size_scale, offset_x, offset_y)

    x, y, s = box["x"], box["y"], box["size"]

    if method == "inpaint":
        frame = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        inpaint_mask = sparkle_inpaint_mask(s)
        full_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        full_mask[y : y + s, x : x + s] = inpaint_mask
        cleaned = cv2.inpaint(frame, full_mask, 3, cv2.INPAINT_TELEA)
        return Image.fromarray(cv2.cvtColor(cleaned, cv2.COLOR_BGR2RGB))

    elif method == "reconstruct":
        frame = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        inpaint_mask = sparkle_inpaint_mask(s)
        cleaned_frame = reconstruct_rows(frame, box, inpaint_mask)
        return Image.fromarray(cv2.cvtColor(cleaned_frame, cv2.COLOR_BGR2RGB))

    else:  # math (alpha unblending)
        output = image.convert("RGBA")
        alphas = alpha_map(mask, s, gain)
        pixels = output.load()
        for row in range(s):
            for col in range(s):
                alpha = alphas[row * s + col]
                if alpha < ALPHA_THRESHOLD:
                    continue
                px = x + col
                py = y + row
                if px >= width or py >= height:
                    continue
                r, g, b, a = pixels[px, py]
                restored = tuple(
                    max(0, min(255, round((channel - alpha * LOGO_VALUE) / (1.0 - alpha))))
                    for channel in (r, g, b)
                )
                pixels[px, py] = (*restored, a)
        return output.convert("RGB")


def veo_watermark_info(width: int, height: int) -> dict[str, int]:
    base = min(width, height)
    size = max(24, min(round(base / 15), base))
    margin = round(base / 10)
    return {
        "size": size,
        "x": max(0, width - margin - size),
        "y": max(0, height - margin - size),
        "width": size,
        "height": size,
    }


def adaptive_video_offset(width: int, height: int) -> int:
    scale_ratio = max(0.3, min(1.5, min(width, height) / 720))
    return round(-24 * scale_ratio)


def sparkle_inpaint_mask(size: int) -> np.ndarray:
    mask = np.zeros((size, size), dtype=np.uint8)
    center = size // 2
    inner = max(4, round(size * 0.28))
    points = np.array(
        [
            [center, 0],
            [center + inner, center - inner],
            [size - 1, center],
            [center + inner, center + inner],
            [center, size - 1],
            [center - inner, center + inner],
            [0, center],
            [center - inner, center - inner],
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(mask, [points], 255)
    return cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1)


def reconstruct_rows(frame: np.ndarray, box: dict[str, int], mask: np.ndarray) -> np.ndarray:
    output = frame.copy()
    x0, y0 = box["x"], box["y"]
    for row in range(box["height"]):
        masked = np.flatnonzero(mask[row])
        if masked.size == 0:
            continue
        left = x0 + int(masked[0])
        right = x0 + int(masked[-1])
        sample_left = max(x0 - 12, left - 8)
        sample_right = min(frame.shape[1] - 1, right + 8)
        left_pixel = frame[y0 + row, sample_left].astype(np.float32)
        right_pixel = frame[y0 + row, sample_right].astype(np.float32)
        for x in range(left, right + 1):
            ratio = (x - left) / max(1, right - left)
            output[y0 + row, x] = np.clip(
                left_pixel * (1 - ratio) + right_pixel * ratio,
                0,
                255,
            ).astype(np.uint8)
    return output


def remove_watermark_from_video(
    input_path: Path,
    output_path: Path,
    mask_path: Path | None = None,
    gain: float = 1.0,
    size_scale: float = 1.0,
    offset_x: int | None = None,
    offset_y: int | None = None,
    preset: str = "veo",
    method: str = "reconstruct",
    progress_callback: callable | None = None,
) -> None:
    if mask_path is None or not Path(mask_path).exists():
        candidates = [
            Path(__file__).parent / "assets" / "bg_96.png",
            Path(__file__).parent / "assets" / "bg_48.png",
            Path(__file__).parent / "bg_96.png",
            Path(__file__).parent / "bg_48.png",
            Path.cwd() / "assets" / "bg_96.png",
            Path.cwd() / "gemini-watermark-remover" / "assets" / "bg_96.png",
        ]
        found = next((c for c in candidates if c.exists()), None)
        if found is None:
            raise FileNotFoundError("Could not find watermark asset bg_96.png")
        mask_path = found

    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {input_path}")

    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    base = veo_watermark_info(width, height)
    if preset == "veo":
        default_offset = adaptive_video_offset(width, height)
    else:
        default_offset = 0
    with Image.open(mask_path) as mask_image:
        success, first_frame = capture.read()
        if not success:
            capture.release()
            raise RuntimeError("Could not read the first video frame")
        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        detected = detect_watermark_box(first_frame, mask_image, base)
        detected_confidently = detected.get("score", 0.0) >= 0.35
        detected_offset = 0 if detected_confidently else default_offset
        box = resolve_box(
            detected,
            width,
            height,
            size_scale,
            detected_offset if offset_x is None else offset_x,
            detected_offset if offset_y is None else offset_y,
        )
        mask = np.asarray(
            mask_image.resize((box["size"], box["size"]), Image.Resampling.BICUBIC).convert("RGB"),
            dtype=np.float32,
        )
    alpha = np.minimum(mask.max(axis=2) / 255.0 * gain, MAX_ALPHA)
    active = alpha >= ALPHA_THRESHOLD
    inpaint_mask = sparkle_inpaint_mask(box["size"])

    temporary = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    temporary_path = Path(temporary.name)
    temporary.close()
    writer = cv2.VideoWriter(
        str(temporary_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        capture.release()
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError("Could not create temporary video output")

    try:
        processed = 0
        while True:
            success, frame = capture.read()
            if not success:
                break

            region = frame[box["y"] : box["y"] + box["height"], box["x"] : box["x"] + box["width"]].astype(np.float32)
            if method == "reconstruct":
                frame = reconstruct_rows(frame, box, inpaint_mask)
            elif method == "inpaint":
                cleaned_region = cv2.inpaint(
                    frame,
                    cv2.copyMakeBorder(
                        inpaint_mask,
                        box["y"],
                        height - box["y"] - box["height"],
                        box["x"],
                        width - box["x"] - box["width"],
                        cv2.BORDER_CONSTANT,
                    ),
                    7,
                    cv2.INPAINT_TELEA,
                )
                frame = cleaned_region
            else:
                restored = (region - alpha[:, :, None] * LOGO_VALUE) / (1.0 - alpha[:, :, None])
                region[active] = np.clip(restored[active], 0, 255)
                frame[box["y"] : box["y"] + box["height"], box["x"] : box["x"] + box["width"]] = region.astype(np.uint8)
            writer.write(frame)
            processed += 1
            if progress_callback:
                progress_callback(processed, frame_count)
            elif frame_count and processed % 30 == 0:
                print(f"Processed {processed}/{frame_count} frames", end="\r")
    finally:
        capture.release()
        writer.release()

    print(f"Processed {processed} frames. Muxing audio...       ")
    ffmpeg_bin = get_ffmpeg_binary()
    if ffmpeg_bin is not None:
        try:
            try:
                subprocess.run(
                    [
                        ffmpeg_bin, "-y", "-i", str(temporary_path), "-i", str(input_path),
                        "-map", "0:v:0?", "-map", "1:a?", "-c:v", "libx264", "-crf", "18",
                        "-preset", "medium", "-c:a", "copy", "-shortest", str(output_path),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except subprocess.CalledProcessError:
                subprocess.run(
                    [
                        ffmpeg_bin, "-y", "-i", str(temporary_path),
                        "-c:v", "libx264", "-crf", "18", "-preset", "medium", str(output_path),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
        except Exception:
            shutil.copyfile(temporary_path, output_path)
    else:
        shutil.copyfile(temporary_path, output_path)

    temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove a Gemini sparkle watermark from an image."
    )
    parser.add_argument("input", type=Path, help="Input image or video")
    parser.add_argument("output", type=Path, help="Output PNG or MP4 path")
    parser.add_argument("--gain", type=float, default=0.6, help="Watermark strength")
    parser.add_argument("--size-scale", type=float, default=1.0)
    parser.add_argument("--offset-x", type=int, default=None)
    parser.add_argument("--offset-y", type=int, default=None)
    parser.add_argument("--preset", choices=("veo", "corner"), default="veo")
    parser.add_argument("--method", choices=("math", "inpaint", "reconstruct"), default="reconstruct")
    parser.add_argument("--mask", type=Path, help="Optional custom logo mask image")
    args = parser.parse_args()

    if args.gain <= 0 or args.size_scale <= 0:
        parser.error("--gain and --size-scale must be greater than zero")

    video_extensions = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
    if args.input.suffix.lower() in video_extensions:
        remove_watermark_from_video(
            args.input,
            args.output,
            args.mask or Path(__file__).parent / "assets" / "bg_96.png",
            gain=args.gain,
            size_scale=args.size_scale,
            offset_x=args.offset_x,
            offset_y=args.offset_y,
            preset=args.preset,
            method=args.method,
        )
        return

    with Image.open(args.input) as image:
        base = watermark_info(*image.size)
        default_mask_name = "bg_48.png" if base["size"] <= 48 else "bg_96.png"
        mask_path = args.mask or Path(__file__).parent / "assets" / default_mask_name
        with Image.open(mask_path) as mask:
            cleaned = remove_watermark(
                image,
                mask,
                gain=args.gain,
                size_scale=args.size_scale,
                offset_x=args.offset_x if args.offset_x is not None else 0,
                offset_y=args.offset_y if args.offset_y is not None else 0,
            )
        cleaned.save(args.output, "PNG")


if __name__ == "__main__":
    main()
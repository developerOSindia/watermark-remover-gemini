# Gemini Watermark Remover

Local Streamlit application for removing Gemini-style sparkle watermarks from images and videos. The project is maintained in the [`developerOSindia/watermark-remover-gemini`](https://github.com/developerOSindia/watermark-remover-gemini) repository.

## What it does

- Processes one image or video at a time, up to 100 MB.
- Detects the likely watermark region and shows its coordinates and match score.
- Provides an optional detection reticle before processing.
- Supports PNG, JPG, JPEG, and WEBP images.
- Supports MP4, MOV, MKV, WEBM, and AVI videos.
- Shows source and cleaned media side by side.
- Provides full-frame, 100% watermark-region crop, and difference-heatmap views for images.
- Preserves the original video audio track when FFmpeg is available.
- Checks several video frames and selects the strongest watermark match before processing.
- Runs locally without cloud uploads, external APIs, or telemetry.

## Run locally

```bash
cd developeros-watermark-studio
python3 -m pip install -r requirements.txt
streamlit run app.py
```

Open the local URL printed by Streamlit, usually `http://localhost:8501`.

The app uses system FFmpeg when available and falls back to the bundled
`imageio-ffmpeg` executable. The `packages.txt` entry installs system FFmpeg
on Streamlit Community Cloud, while `requirements.txt` provides the Python
fallback. Verify the local command with:

```bash
ffmpeg -version
```

## Processing controls

### Processing method

- **OpenCV inpaint**: recommended default. Fills the marked region from surrounding texture and is usually best for detailed or irregular backgrounds.
- **Line reconstruction**: rebuilds marked rows from nearby clean pixels. It can be useful for simple backgrounds but may flatten stripes or strong texture.
- **Alpha unblending**: reverses a transparent logo mathematically. Best when the source watermark is a true alpha blend.

### Watermark strength

The default value is `0.60`. Increase it if a watermark trace remains. Lower it if surrounding pixels appear too strongly altered. Start with small changes.

### Mask scale

The default value is `1.00`, matching the standard detected logo size. Increase it for a larger watermark or decrease it for a smaller one.

### Video alignment

- **Veo**: applies the adaptive inset used for Veo-style video marks.
- **Corner**: targets the unshifted lower-right corner.

## Automatic safety thresholds

The processing engine uses two safeguards:

- Alpha values below `0.002` are ignored, so pixels outside the active mask are left unchanged.
- Alpha values are capped at `0.99` to avoid unstable division during mathematical restoration.

These limits are automatic and do not need to be changed for normal use.

## Command-line engine

The underlying Python engine can also be used without Streamlit:

```bash
python3 remove_watermark.py input.png cleaned.png
python3 remove_watermark.py input.mp4 cleaned.mp4
```

Useful video options:

```bash
python3 remove_watermark.py input.mp4 cleaned.mp4 \
	--method inpaint \
	--gain 0.6 \
	--size-scale 1.0 \
	--preset veo
```

Available methods are `inpaint` (default), `reconstruct`, and `math`. Available presets are `veo` and `corner`.

## Project structure

```text
app.py                 Streamlit interface
remove_watermark.py    Image/video processing engine
assets/bg_48.png       Small watermark mask
assets/bg_96.png       Large watermark mask
requirements.txt       Python dependencies
DESIGN.md              UI design contract
```

## Privacy

Uploaded media is written to temporary files on the local machine while the current Streamlit session runs. The app does not send media to a server or third-party processing API.

## License

MIT License. Copyright (c) 2026 developerOSindia.

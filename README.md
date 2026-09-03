# Developeros Cleanroom

A Streamlit interface for the existing Python watermark-removal engine. It processes images and videos locally and preserves video audio through FFmpeg.

## Run

```bash
cd developeros-watermark-studio
python3 -m pip install -r requirements.txt
streamlit run app.py
```

FFmpeg must be installed and available on `PATH` for video exports.

## Features & Controls

- **Precision Loupe (4× Zoom)**: Real-time magnified before/after inspection of the target watermark sector with exact coordinate readouts.
- **Instant Unblending**: Mathematical alpha inversion computed in real-time as sliders are adjusted.
- **Fine-Tuning Offsets**: Nudge controls for horizontal (`ΔX`) and vertical (`ΔY`) alignment alongside gain and scale.
- **Alpha Difference Heatmap**: Visual verification proving that untouched pixels remain 100% bit-for-bit identical.
- **Video Frame 0 Stager**: Preview and dial in alignment on a live video frame before rendering the full clip.
- **Live Frame Progress**: Frame-by-frame progress bar with percentage, ETA, and lossless audio remuxing via FFmpeg.
- **Export Options**: Lossless PNG, high-res JPEG, and clean MP4 downloads.
- **1-Click Sample Media**: Built-in authentic Gemini test image to verify setup instantly without hunting for files.
- **100% Private & On-Device**: Zero external API calls, cloud telemetry, or network leaks.

import os
import subprocess
import tempfile
import logging
from fastapi import FastAPI, UploadFile
import whisper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stt")

app = FastAPI()
_model = None

INITIAL_PROMPT = (
    "Commands: move left, move right, move up, move down, move forward, "
    "move back, grasp, release, open gripper, close gripper, "
    "spawn apple, spawn mug, spawn bottle, spawn sphere, spawn cube, "
    "spawn cylinder, spawn can, reset environment, stop."
)

def get_model():
    global _model
    if _model is None:
        logger.info("Loading Whisper small.en model...")
        _model = whisper.load_model("small.en")
        logger.info("Whisper model loaded")
    return _model

def _normalize_audio(input_path):
    """Normalize to 16kHz mono WAV with consistent volume."""
    output_path = input_path + ".wav"
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", input_path,
                "-ar", "16000",
                "-ac", "1",
                "-sample_fmt", "s16",
                "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
                output_path,
            ],
            capture_output=True, check=True, timeout=30,
        )
        return output_path
    except Exception as e:
        logger.warning(f"Audio normalization failed, using raw: {e}")
        return input_path

@app.post("/transcribe")
async def transcribe(audio: UploadFile):
    data = await audio.read()
    suffix = os.path.splitext(audio.filename or ".webm")[1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        normalized = _normalize_audio(tmp)
        model = get_model()
        result = model.transcribe(
            normalized,
            language="en",
            temperature=0.0,
            initial_prompt=INITIAL_PROMPT,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            verbose=False,
        )
        text = result["text"].strip()
        logger.info(f"Transcribed: \"{text}\"")
        return {"text": text}
    finally:
        for p in [tmp, tmp + ".wav"]:
            if os.path.exists(p):
                os.unlink(p)

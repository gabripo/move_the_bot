import os
import tempfile
import logging
from fastapi import FastAPI, UploadFile
import whisper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stt")

app = FastAPI()
_model = None

def get_model():
    global _model
    if _model is None:
        logger.info("Loading Whisper tiny model...")
        _model = whisper.load_model("tiny")
        logger.info("Whisper model loaded")
    return _model

@app.post("/transcribe")
async def transcribe(audio: UploadFile):
    data = await audio.read()
    suffix = os.path.splitext(audio.filename or ".webm")[1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        model = get_model()
        result = model.transcribe(tmp, language="en")
        text = result["text"].strip()
        logger.info(f"Transcribed: \"{text}\"")
        return {"text": text}
    finally:
        os.unlink(tmp)

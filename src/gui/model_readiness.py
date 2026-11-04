"""Cache hints without importing or initializing AI runtimes."""
from pathlib import Path
from src.config import MODEL_DIR
from src.separation.models import get_model


def model_readiness(identifier: str, cache: Path = MODEL_DIR) -> str:
    model = get_model(identifier)
    present = (cache / model.filename).is_file()
    state = "Primary model file is present." if present else "Primary model is missing; a download is needed if separation runs."
    return (f"{model.display_name}\nModel cache: {cache}\n{state}\n"
            "The separation backend checks model data and may download missing weights or auxiliary files. "
            "A present primary file does not guarantee a complete or valid cache.")

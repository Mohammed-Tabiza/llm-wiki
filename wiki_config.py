import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)


def _clean_value(value: str) -> str:
    value = value.strip()
    if value.startswith(("r'", 'r"', "R'", 'R"')):
        value = value[1:]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value


def _path_from_env(name: str) -> Path | None:
    value = os.getenv(name)
    if not value:
        return None

    value = value.strip()
    if value.startswith("Path(") and value.endswith(")"):
        value = value.removeprefix("Path(").removesuffix(")")

    if "/" in value:
        base_name, relative_value = value.split("/", 1)
        base_path = globals().get(base_name.strip())
        if isinstance(base_path, Path):
            return base_path / _clean_value(relative_value)

    return Path(_clean_value(value))


MODEL_NAME = os.environ["MODEL_NAME"]
API_BASE = os.getenv("API_BASE")
API_KEY = os.getenv("API_KEY")

if API_BASE:
    os.environ["OPENAI_BASE_URL"] = API_BASE
    os.environ["OPENAI_API_BASE"] = API_BASE

if API_KEY:
    os.environ["OPENAI_API_KEY"] = API_KEY

OBSIDIAN_DIR = _path_from_env("OBSIDIAN_DIR") or Path()
RAW_DIR = _path_from_env("RAW_DIR") or OBSIDIAN_DIR / "Clippings"
WIKI_DIR = _path_from_env("WIKI_DIR") or OBSIDIAN_DIR / "AI Wiki"
SOURCES_DIR = _path_from_env("SOURCES_DIR") or WIKI_DIR / "sources"
TOPICS_DIR = _path_from_env("TOPICS_DIR") or WIKI_DIR / "topics"
ENTITIES_DIR = _path_from_env("ENTITIES_DIR") or WIKI_DIR / "entities"
INDEX_FILE = _path_from_env("INDEX_FILE") or WIKI_DIR / "index.md"
REPORT_FILE = _path_from_env("REPORT_FILE") or WIKI_DIR / "lint_report.md"
VAULT_NAME = (
    OBSIDIAN_DIR.name
    if os.getenv("VAULT_NAME") == "OBSIDIAN_DIR.name"
    else os.getenv("VAULT_NAME", OBSIDIAN_DIR.name)
)


def get_chat_model_kwargs(max_tokens: int) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "model": MODEL_NAME,
        "temperature": 0,
    }

    if MODEL_NAME.startswith("openai:"):
        kwargs["max_tokens"] = max_tokens
        if API_BASE:
            kwargs["base_url"] = API_BASE
        if API_KEY:
            kwargs["api_key"] = API_KEY
    else:
        kwargs["num_predict"] = max_tokens

    return kwargs

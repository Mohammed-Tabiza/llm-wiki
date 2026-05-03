import json
import re
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain.chat_models import init_chat_model
from fastapi.responses import StreamingResponse
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

MODEL_NAME = "ollama:gemma4:31b-cloud"
OBSIDIAN_DIR = Path(r"C:\Users\moham\Documents\Obsidian Vault")
WIKI_DIR = OBSIDIAN_DIR / "AI Wiki"
INDEX_FILE = WIKI_DIR / "index.md"
VAULT_NAME = OBSIDIAN_DIR.name

ANSWER_PROMPT = """
You answer questions from a local Obsidian wiki.

Use only the provided wiki context.

Rules:
- Answer in the same language as the question.
- Cite claims inline with the clickable markdown links included in the context.
- If the wiki does not contain enough information, say so plainly.
- Keep answers concise and practical.
- Do not invent page paths or citations.

Question:
{question}

Wiki context:
{context}
"""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    thread_id: str


class PageSummary(BaseModel):
    path: str
    title: str
    kind: str


class PagesResponse(BaseModel):
    index_exists: bool
    pages: list[PageSummary]


class PageResponse(BaseModel):
    path: str
    title: str
    content: str
    obsidian_url: str


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def build_wiki_path(path: Path) -> str:
    return str(path.relative_to(WIKI_DIR).with_suffix("")).replace("\\", "/")


def build_wiki_link(wiki_path: str) -> str:
    return f"[[{wiki_path}]]"


def build_obsidian_uri(file_path: Path) -> str:
    vault_name = quote(VAULT_NAME)
    vault_relative_path = quote(str(file_path.relative_to(OBSIDIAN_DIR)).replace("\\", "/"))
    return f"obsidian://open?vault={vault_name}&file={vault_relative_path}"


def build_markdown_link(label: str, file_path: Path) -> str:
    return f"[{label}]({build_obsidian_uri(file_path)})"


def get_page_path(wiki_path: str) -> Path:
    page_path = (WIKI_DIR / f"{wiki_path}.md").resolve()
    wiki_root = WIKI_DIR.resolve()

    if page_path != wiki_root and wiki_root not in page_path.parents:
        raise HTTPException(status_code=400, detail="Invalid wiki path.")

    return page_path


def get_wiki_paths() -> list[str]:
    return sorted(
        build_wiki_path(path)
        for path in WIKI_DIR.rglob("*.md")
        if path != INDEX_FILE
    )


def get_page_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            return line.removeprefix("# ").strip()
    return fallback.rsplit("/", maxsplit=1)[-1]


def read_index() -> str:
    return "\n".join(
        [
            f"Citation: {build_markdown_link('index', INDEX_FILE)}",
            read_text(INDEX_FILE),
        ]
    )


def read_page(wiki_path: str) -> str:
    page_path = get_page_path(wiki_path)
    return "\n".join(
        [
            f"Page: {wiki_path}",
            f"Citation: {build_markdown_link(wiki_path, page_path)}",
            read_text(page_path),
        ]
    )


model = init_chat_model(
    model=MODEL_NAME,
    temperature=0,
    num_predict=512,
)
answer_prompt = ChatPromptTemplate.from_template(ANSWER_PROMPT)
answer_chain = answer_prompt | model

app = FastAPI(title="LLM Wiki API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "wiki_dir": str(WIKI_DIR),
        "index_exists": INDEX_FILE.exists(),
    }


@app.get("/api/pages", response_model=PagesResponse)
def pages() -> PagesResponse:
    page_summaries: list[PageSummary] = []

    for wiki_path in get_wiki_paths():
        page_path = get_page_path(wiki_path)
        content = read_text(page_path)
        page_summaries.append(
            PageSummary(
                path=wiki_path,
                title=get_page_title(content, wiki_path),
                kind=wiki_path.split("/", maxsplit=1)[0],
            )
        )

    return PagesResponse(index_exists=INDEX_FILE.exists(), pages=page_summaries)


@app.get("/api/page/{wiki_path:path}", response_model=PageResponse)
def page(wiki_path: str) -> PageResponse:
    page_path = get_page_path(wiki_path)
    if not page_path.exists():
        raise HTTPException(status_code=404, detail="Wiki page not found.")

    content = read_text(page_path)
    return PageResponse(
        path=wiki_path,
        title=get_page_title(content, wiki_path),
        content=content,
        obsidian_url=build_obsidian_uri(page_path),
    )


def tokenize(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", value.lower())
        if token not in {"the", "and", "for", "avec", "dans", "des", "les", "une", "est"}
    }


def score_page(question_tokens: set[str], wiki_path: str, content: str) -> int:
    page_text = f"{wiki_path}\n{content}".lower()
    score = 0

    for token in question_tokens:
        if token in wiki_path.lower():
            score += 6
        score += min(page_text.count(token), 4)

    return score


def build_answer_context(question: str, max_pages: int = 4) -> str:
    question_tokens = tokenize(question)
    scored_pages: list[tuple[int, str]] = []

    for wiki_path in get_wiki_paths():
        content = read_text(get_page_path(wiki_path))
        scored_pages.append((score_page(question_tokens, wiki_path, content), wiki_path))

    selected_paths = [
        wiki_path
        for score, wiki_path in sorted(scored_pages, key=lambda item: item[0], reverse=True)
        if score > 0
    ][:max_pages]

    if not selected_paths:
        selected_paths = [wiki_path for _, wiki_path in scored_pages[:max_pages]]

    context_blocks = [read_index()]
    context_blocks.extend(read_page(wiki_path) for wiki_path in selected_paths)
    return "\n\n---\n\n".join(context_blocks)


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    thread_id = request.thread_id or str(uuid4())
    context = build_answer_context(request.message)
    result = answer_chain.invoke(
        {
            "question": request.message,
            "context": context,
        }
    )

    return ChatResponse(answer=result.content, thread_id=thread_id)


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    thread_id = request.thread_id or str(uuid4())

    def stream_events():
        yield json.dumps({"type": "thread", "thread_id": thread_id}) + "\n"
        yield json.dumps({"type": "status", "message": "Searching wiki"}) + "\n"
        context = build_answer_context(request.message)
        yield json.dumps({"type": "status", "message": "Answering"}) + "\n"

        for chunk in answer_chain.stream(
            {
                "question": request.message,
                "context": context,
            }
        ):
            if chunk.content:
                yield json.dumps({"type": "token", "content": chunk.content}) + "\n"

        yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(stream_events(), media_type="application/x-ndjson")

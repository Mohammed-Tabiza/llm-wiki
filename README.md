# LLM Wiki
A local LLM wiki maintainer using Ollama and LangChain that reads markdown files from your Obsidian `Clippings` folder and rebuilds a wiki inside `AI Wiki`. This is based on Andrej Karpathy’s idea. It includes:

- `llm_wiki_builder.py`: rebuilds the wiki from raw markdown sources
- `llm_wiki_to_markdown.py`: converts PDF and Word documents to markdown sources
- `llm_wiki_linter.py`: checks and cleans the generated wiki
- `llm_wiki_maintainer.py`: a LangChain agent that answers questions about your knowledge base

It still does not implement the full incremental maintenance flow from the idea document, but the builder, linter, and query agent follow the same pattern at a smaller scale.

You can watch the videos on my YouTube:

- [Build the wiki](https://youtu.be/l4EzuMKmeA0?si=wqP4O_w3a-99mstQ)
- [Query the wiki](https://youtu.be/4D8FjzJXJd4)

# Pre-requisites
Install Ollama on your local machine from the [official website](https://ollama.com/). And then pull the Gemma model:

```bash
ollama pull gemma4:31b-cloud
```

Install the dependencies using pip:

```bash
pip install -r requirements.txt
```

Create a `.env` file from `.env.example` and set your Obsidian vault path there:

```env
MODEL_NAME="openai:Qwen/Qwen3-14B"
API_BASE="https://example.invalid/v1"
API_KEY="no-needed"
OBSIDIAN_DIR=Path(r"PUT_YOUR_OBSIDIAN_PATH")
WIKI_DIR=OBSIDIAN_DIR / "AI Wiki"
```

# Run
Convert a PDF or Word file to a markdown source in `Clippings`:

```bash
python llm_wiki_to_markdown.py "path/to/document.pdf"
python llm_wiki_to_markdown.py "path/to/document.docx"
```

Build the wiki:

```bash
python llm_wiki_builder.py
```

Lint the generated wiki:

```bash
python llm_wiki_linter.py
```

Apply safe mechanical cleanup before linting:

```bash
python llm_wiki_linter.py --apply
```

Run the question-answering agent:

```bash
streamlit run llm_wiki_maintainer.py
```

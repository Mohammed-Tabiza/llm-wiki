import argparse
import re
import shutil
from pathlib import Path

from markdownify import markdownify

from wiki_config import RAW_DIR

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".docm", ".md", ".markdown"}


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower().strip())
    return value.strip("-") or "untitled"


def normalize_markdown(content: str) -> str:
    lines = [line.rstrip() for line in content.splitlines()]
    normalized = "\n".join(lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip() + "\n"


def get_output_path(input_path: Path, output: Path | None, output_dir: Path) -> Path:
    if output:
        return output

    return output_dir / f"{slugify(input_path.stem)}.md"


def convert_pdf_to_markdown(
    input_path: Path,
    *,
    pages: str | None = None,
    table_method: str | None = None,
) -> str:
    import edgeparse

    kwargs = {"format": "markdown"}
    if pages:
        kwargs["pages"] = pages
    if table_method:
        kwargs["table_method"] = table_method

    result = edgeparse.convert(str(input_path), **kwargs)
    if isinstance(result, str):
        return result

    markdown = getattr(result, "markdown", None)
    if isinstance(markdown, str):
        return markdown

    return str(result)


def convert_word_to_markdown(input_path: Path) -> str:
    import mammoth

    with input_path.open("rb") as document:
        result = mammoth.convert_to_html(document)

    return markdownify(result.value, heading_style="ATX")


def convert_to_markdown(
    input_path: Path,
    *,
    pages: str | None = None,
    table_method: str | None = None,
) -> str:
    suffix = input_path.suffix.lower()

    if suffix == ".pdf":
        return convert_pdf_to_markdown(
            input_path,
            pages=pages,
            table_method=table_method,
        )

    if suffix in {".docx", ".docm"}:
        return convert_word_to_markdown(input_path)

    if suffix in {".md", ".markdown"}:
        return input_path.read_text(encoding="utf-8")

    if suffix == ".doc":
        raise ValueError(
            "Legacy .doc files are not supported directly. Save the file as .docx first."
        )

    supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
    raise ValueError(f"Unsupported file type '{suffix}'. Supported types: {supported}.")


def write_markdown(
    input_path: Path,
    output_path: Path,
    *,
    pages: str | None = None,
    table_method: str | None = None,
    overwrite: bool = False,
) -> Path:
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists. Use --overwrite to replace it.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if input_path.suffix.lower() in {".md", ".markdown"}:
        shutil.copyfile(input_path, output_path)
    else:
        markdown = convert_to_markdown(
            input_path,
            pages=pages,
            table_method=table_method,
        )
        output_path.write_text(normalize_markdown(markdown), encoding="utf-8")

    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a PDF or Word document to Markdown for the LLM wiki."
    )
    parser.add_argument("input", type=Path, help="PDF, DOCX, DOCM, or Markdown file to convert.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Markdown output file. Defaults to RAW_DIR/<input-name>.md.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=RAW_DIR,
        help=f"Directory used when --output is omitted. Defaults to {RAW_DIR}.",
    )
    parser.add_argument(
        "--pages",
        help='PDF page range for EdgeParse, for example "1-5". Ignored for Word files.',
    )
    parser.add_argument(
        "--table-method",
        help="EdgeParse table detection method for PDFs. Ignored for Word files.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the output file if it already exists.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = args.input.expanduser().resolve()

    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    output_path = get_output_path(input_path, args.output, args.output_dir)
    output_path = output_path.expanduser().resolve()

    try:
        written_path = write_markdown(
            input_path,
            output_path,
            pages=args.pages,
            table_method=args.table_method,
            overwrite=args.overwrite,
        )
    except (FileExistsError, ValueError) as error:
        raise SystemExit(str(error)) from error

    print(f"Wrote {written_path}")


if __name__ == "__main__":
    main()

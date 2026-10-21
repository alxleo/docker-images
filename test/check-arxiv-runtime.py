"""Exercise the installed arXiv PDF dependencies inside the built image."""

import sys
from importlib.metadata import version

import pymupdf
import pymupdf4llm

assert version("arxiv-mcp-server") == sys.argv[1]
assert version("mcp").startswith("1.")

with pymupdf.open() as document:
    page = document.new_page()
    page.insert_text((72, 72), "arXiv PDF smoke")
    markdown = pymupdf4llm.to_markdown(document, show_progress=False)

assert "arXiv PDF smoke" in markdown, markdown
print(
    f"arXiv {version('arxiv-mcp-server')}: "
    f"PDF conversion passed with PyMuPDF {version('pymupdf')}"
)

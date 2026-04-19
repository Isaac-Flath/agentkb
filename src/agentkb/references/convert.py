"""Converters: turn fetched bytes into indexable markdown.

Phase 1 supports HTML → Markdown. PDF conversion lives here when it's added.
"""

from __future__ import annotations


def html_to_markdown(html: str) -> str:
    """Extract the main article from HTML and convert to markdown.

    Uses BeautifulSoup to strip site chrome (nav/footer/aside/script/style)
    and locate the article container, then ``markdownify`` to emit clean
    markdown. Unknown custom elements (e.g. distill's ``<d-cite>``) are
    rendered by their text content, not kept as raw tags.
    """
    from bs4 import BeautifulSoup
    from markdownify import markdownify

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()

    root = _locate_article(soup) or soup.body or soup
    md = markdownify(str(root), heading_style="ATX", bullets="-")

    # Collapse runs of blank lines markdownify sometimes leaves behind.
    import re
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


def _locate_article(soup):
    """Find the most likely article container in a page."""
    for selector in ("article", "main", '[role="main"]', ".post", ".content", "#content"):
        el = soup.select_one(selector)
        if el:
            return el
    return None

"""Turns PDF pages into sentence-sized chunks that sound right when spoken."""

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

from pdfdesk.document import PdfDocument

MAX_CHARS = 400
MIN_CHARS = 25
MARGIN = 0.08
FURNITURE_SAMPLE = 24
FURNITURE_SHARE = 0.3
HEADING_SIZE_RATIO = 1.15
HEADING_MAX_CHARS = 120
BULLETS = set("•▪◦■●‣⁃·")
ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.", "e.g.", "i.e.",
    "fig.", "figs.", "no.", "nos.", "vol.", "pp.", "p.", "ed.", "eds.", "inc.", "ltd.", "co.",
    "cf.", "al.", "approx.", "dept.", "ch.", "sec.", "jan.", "feb.", "mar.", "apr.", "jun.",
    "jul.", "aug.", "sep.", "sept.", "oct.", "nov.", "dec.",
}
PAGE_NUMBER = re.compile(r"^(page\s*)?(\d+|[ivxlcdm]+)(\s*(/|of)\s*\d+)?$", re.I)
SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*$")


@dataclass
class Chunk:
    text: str
    page: int
    word: int
    end_page: int
    end_word: int
    rects: dict = field(default_factory=dict)
    heading: bool = False


@dataclass
class _Line:
    words: list
    text: str
    y0: float
    y1: float


@dataclass
class _Token:
    text: str
    sources: list  # [(page, Word), ...]
    ends_line: bool = False


def page_lines(document, index):
    lines, key = [], None
    for word in document.words(index):
        word_key = (word.block, word.line)
        if word_key != key:
            lines.append([])
            key = word_key
        lines[-1].append(word)
    return [
        _Line(
            words,
            " ".join(w.text for w in words),
            min(w.rect[1] for w in words),
            max(w.rect[3] for w in words),
        )
        for words in lines
    ]


def _furniture_key(text):
    return re.sub(r"\d+", "#", text.lower()).strip()


def _in_margin(line, height):
    return line.y1 <= height * MARGIN or line.y0 >= height * (1 - MARGIN)


def find_furniture(document):
    """Find running headers and footers: margin text repeated across many pages."""
    total = len(document)
    if total < 3:
        return set()
    sample = sorted({round(i * (total - 1) / (min(total, FURNITURE_SAMPLE) - 1)) for i in range(min(total, FURNITURE_SAMPLE))})
    counts = Counter()
    for index in sample:
        height = document.page(index).rect.height
        seen = {_furniture_key(l.text) for l in page_lines(document, index) if _in_margin(l, height)}
        counts.update(seen)
    needed = max(3, len(sample) * FURNITURE_SHARE)
    return {key for key, count in counts.items() if count >= needed}


def _page_styles(page):
    """Return [(bbox, all_bold, size)] for each text line, plus the page's body size and bold share."""
    styles, sizes = [], []
    bold_chars = total_chars = 0
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            bold = all("bold" in s.get("font", "").lower() or int(s.get("flags", 0)) & 16 for s in spans)
            size = max(s.get("size", 0) for s in spans)
            styles.append((PdfDocument.to_display(page, line["bbox"]), bold, size))
            for span in spans:
                count = len(span["text"].strip())
                sizes.extend([round(span.get("size", 0), 1)] * min(count, 200))
                total_chars += count
                if bold:
                    bold_chars += count
    body = statistics.median(sizes) if sizes else 0
    return styles, body, (bold_chars / total_chars if total_chars else 0)


def _is_heading(line, styles, body, bold_share):
    if len(line.text) > HEADING_MAX_CHARS or not any(c.isalpha() for c in line.text):
        return False
    first = line.words[0].rect
    cx, cy = (first[0] + first[2]) / 2, (first[1] + first[3]) / 2
    for bbox, bold, size in styles:
        if bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]:
            large = body and size >= body * HEADING_SIZE_RATIO
            # On a mostly bold page, bold doesn't say anything about structure.
            return large or (bold and bold_share < 0.5)
    return False


def _ends_sentence(text):
    return bool(SENTENCE_END.search(text)) and text.lower().rstrip("\"'”’)]") not in ABBREVIATIONS


def _starts_sentence(text):
    first = text.lstrip("\"'“‘([")[:1]
    return first.isupper() or first.isdigit()


class ChunkBuilder:
    """Feed pages in order. Sentences carry across page breaks until they end."""

    def __init__(self, document, furniture=frozenset()):
        self.document = document
        self.furniture = furniture
        self.chunks = []
        self._tokens = []

    def feed(self, index, first_word=0, last_word=None):
        page = self.document.page(index)
        styles, body, bold_share = _page_styles(page)
        height = page.rect.height
        heading = []
        previous_block = None
        for line in page_lines(self.document, index):
            if line.words[-1].index < first_word or (last_word is not None and line.words[0].index > last_word):
                continue
            if _in_margin(line, height) and (
                PAGE_NUMBER.match(line.text.strip()) or _furniture_key(line.text) in self.furniture
            ):
                continue
            words = [w for w in line.words if w.index >= first_word and (last_word is None or w.index <= last_word)]
            if _is_heading(line, styles, body, bold_share):
                if heading and heading[-1].block != words[0].block:
                    self._emit_heading(index, heading)
                    heading = []
                heading.extend(words)
                continue
            if heading:
                self._emit_heading(index, heading)
                heading = []
            block = words[0].block
            if previous_block is not None and block != previous_block and self._tokens:
                if _ends_sentence(self._tokens[-1].text):
                    self._flush()
            previous_block = block
            self._add_line(index, words)
        if heading:
            self._emit_heading(index, heading)

    def finish(self):
        self._flush()
        return self.chunks

    def _add_line(self, index, words):
        for position, word in enumerate(words):
            text = word.text.strip()
            if not text:
                continue
            if all(c in BULLETS for c in text):
                self._flush()
                continue
            text = text.lstrip("".join(BULLETS)) or text
            if position == 0 and self._merge_hyphenated(text, index, word):
                continue
            previous = self._tokens[-1] if self._tokens else None
            if previous and _ends_sentence(previous.text) and _starts_sentence(text):
                self._flush(respect_minimum=True)
            self._tokens.append(_Token(text, [(index, word)]))
            self._split_if_long()
        if self._tokens:
            self._tokens[-1].ends_line = True

    def _merge_hyphenated(self, text, index, word):
        """Rejoin 'bet-' + 'ween' from printed line wrapping; leave '32-bit' alone."""
        if not self._tokens:
            return False
        previous = self._tokens[-1]
        if previous.ends_line and re.search(r"[A-Za-z]{2}-$", previous.text) and re.match(r"[a-z]{2}", text):
            previous.text = previous.text[:-1] + text
            previous.sources.append((index, word))
            previous.ends_line = False
            return True
        return False

    def _length(self):
        return sum(len(t.text) + 1 for t in self._tokens)

    def _split_if_long(self):
        if self._length() <= MAX_CHARS:
            return
        # Break a very long sentence at the latest pause in its second half.
        cut = None
        for i in range(len(self._tokens) - 1, len(self._tokens) // 2, -1):
            if self._tokens[i].text[-1] in ",;:—":
                cut = i + 1
                break
        cut = cut or len(self._tokens) - 1
        head, self._tokens = self._tokens[:cut], self._tokens[cut:]
        self._emit(head, False)

    def _flush(self, respect_minimum=False):
        if not self._tokens or (respect_minimum and self._length() < MIN_CHARS):
            return
        tokens, self._tokens = self._tokens, []
        self._emit(tokens, False)

    def _emit_heading(self, index, words):
        self._flush()
        self._emit([_Token(w.text, [(index, w)]) for w in words if w.text.strip()], True)

    def _emit(self, tokens, heading):
        text = " ".join(t.text for t in tokens).strip()
        if not any(c.isalnum() for c in text):
            return
        if heading and text[-1] not in ".!?:":
            text += "."
        sources = [source for token in tokens for source in token.sources]
        rects = {}
        for page, word in sources:
            rows = rects.setdefault(page, [])
            line_key = (word.block, word.line)
            if rows and rows[-1][0] == line_key:
                r = rows[-1][1]
                rows[-1] = (line_key, (min(r[0], word.rect[0]), min(r[1], word.rect[1]), max(r[2], word.rect[2]), max(r[3], word.rect[3])))
            else:
                rows.append((line_key, tuple(word.rect)))
        self.chunks.append(
            Chunk(
                text=text,
                page=sources[0][0],
                word=sources[0][1].index,
                end_page=sources[-1][0],
                end_word=sources[-1][1].index,
                rects={page: [r for _, r in rows] for page, rows in rects.items()},
                heading=heading,
            )
        )


def first_chunk_at(chunks, page, word):
    """Index of the chunk that contains or follows a word, or None if it is still unbuilt."""
    for i, chunk in enumerate(chunks):
        if (chunk.end_page, chunk.end_word) >= (page, word):
            return i
    return None

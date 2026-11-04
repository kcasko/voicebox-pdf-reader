"""Turns PDF pages into sentence-sized chunks that sound right when spoken."""

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

from pdfdesk.document import PdfDocument

MAX_CHARS = 400
MIN_CHARS = 25
MARGIN = 0.08
FURNITURE_SAMPLE = 24
FURNITURE_SHARE = 0.3
HEADING_SIZE_RATIO = 1.15
HEADING_MAX_CHARS = 120
FOOTNOTE_SIZE_RATIO = 0.85
FOOTNOTE_ZONE = 0.7
BULLETS = set("•▪◦■●‣⁃·")
TABLE_CELL_GAP = 12
TABLE_CELL_WORDS = 6
ROW_TOLERANCE = 2
# Words that keep their hyphen when a line break falls after them: "self-service", not "selfservice".
COMPOUND_PREFIXES = {"self", "well", "non", "co", "cross", "long", "short", "high", "low", "full", "part", "semi", "anti", "multi", "open", "real", "time"}
ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.", "e.g.", "i.e.",
    "fig.", "figs.", "no.", "nos.", "vol.", "pp.", "p.", "ed.", "eds.", "inc.", "ltd.", "co.",
    "cf.", "al.", "approx.", "dept.", "ch.", "sec.", "jan.", "feb.", "mar.", "apr.", "jun.",
    "jul.", "aug.", "sep.", "sept.", "oct.", "nov.", "dec.", "eq.", "eqs.", "ref.", "refs.",
}
# A dotted acronym usually carries on ("the U.S. Army") unless one of these starts the next sentence.
SENTENCE_STARTERS = {
    "A", "An", "The", "This", "That", "These", "Those", "It", "He", "She", "They", "We", "You", "I",
    "In", "On", "At", "As", "For", "But", "And", "However", "Although", "When", "While", "If", "There",
}
PAGE_NUMBER = re.compile(r"^(page\s*)?(\d+|[ivxlcdm]+)(\s*(/|of)\s*\d+)?$", re.I)
SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*$")
INITIAL = re.compile(r"^[A-Z]\.$")
ACRONYM = re.compile(r"^(?:[A-Za-z]\.){2,}$")
LIST_MARKER = re.compile(r"^\d{1,3}[.)]$")
CONTENTS_WORD = re.compile(r"(?:^|\s)(?:table of )?contents(?:$|\s)", re.I)
ENDS_IN_PAGE_NUMBER = re.compile(r"(?:\.{2,}|\s)\s*(?:\d{1,4}|[ivxlc]+)$", re.I)
CONTENTS_SHARE = 0.5
CONTENTS_MIN_LINES = 4
CONTENTS_RISING_SHARE = 0.9
ONLY_NUMBERS = re.compile(r"^[\d\s.,:;()-]+$")
# Fonts often store bullets in the private-use part of Unicode, which has no sound.
PRIVATE_USE = re.compile("[\ue000-\uf8ff]")
LINK_WORDS = "a link"
REFERENCE_HEADING = re.compile(r"^(?:[\dIVX]+\.?\s+)?(?:references|bibliography|works cited|literature cited)\.?$", re.I)

# Column detection: a gutter is an empty vertical strip in the middle part of the page.
GUTTER_MIN_WIDTH = 8
GUTTER_ZONE = (0.2, 0.8)
GUTTER_MAX_COVERAGE = 0.08
WIDE_LINE_SHARE = 0.6
COLUMN_MIN_LINES = 2
COLUMN_MIN_WORDS = 4

# Spoken text
LATIN_END = 0x250
URL = re.compile(r"\b(?:https?://|www\.)\S+", re.I)
NUMBERED_CITATION = re.compile(r"\s*\[\s*\d+(?:\s*[,;–-]\s*\d+)*\s*\]")
_AUTHOR_YEAR = r"[A-Z][\w'’-]+(?:\s+(?:et\s+al\.?|(?:and|&)\s+[A-Z][\w'’-]+))?,?\s+(?:19|20)\d{2}[a-z]?(?:,\s*pp?\.\s*\d+)?"
AUTHOR_CITATION = re.compile(rf"\s*\((?:see\s+)?{_AUTHOR_YEAR}(?:\s*;\s*{_AUTHOR_YEAR})*\)")
YEAR_CITATION = re.compile(r"\s*\((?:19|20)\d{2}[a-z]?\)")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
CURRENCIES = {"$": ("dollar", "cent"), "€": ("euro", "cent"), "£": ("pound", "penny")}
MAGNITUDES = {"k": "thousand", "m": "million", "b": "billion"}
SPOKEN_WORDS = [
    (re.compile(r"\bEqs\.\s*(?=\d)"), "equations "),
    (re.compile(r"\bEq\.\s*(?=\d)"), "equation "),
    (re.compile(r"\bFigs\.\s*(?=\d)"), "figures "),
    (re.compile(r"\bFig\.\s*(?=\d)"), "figure "),
    (re.compile(r"\bpp\.\s*(?=\d)"), "pages "),
    (re.compile(r"\bp\.\s*(?=\d)"), "page "),
    (re.compile(r"\bNo\.\s*(?=\d)"), "number "),
    (re.compile(r"\be\.g\.,?", re.I), "for example"),
    (re.compile(r"\bi\.e\.,?", re.I), "that is"),
    (re.compile(r"\bvs\.", re.I), "versus"),
    (re.compile(r"\betc\.", re.I), "et cetera"),
    (re.compile(r"\bet al\.", re.I), "et al"),
    (re.compile(r"\bC\+\+"), "C plus plus"),
    (re.compile(r"\bC#"), "C sharp"),
    (re.compile(r"\s&\s"), " and "),
    (re.compile(r"\s=\s"), " equals "),
    (re.compile(r"\s≥\s"), " is at least "),
    (re.compile(r"\s≤\s"), " is at most "),
    (re.compile(r"\s≠\s"), " is not equal to "),
    (re.compile(r"\s≈\s"), " is about "),
    (re.compile(r"(?<=\d)\s?%"), " percent"),
    (re.compile(r"(?<=\d)\s?–\s?(?=\d)"), " to "),
]


def _spoken_year(year):
    if 2000 <= year <= 2009:
        return str(year)
    return f"{year // 100} {year % 100:02d}" if year % 100 >= 10 else str(year)


def _spoken_date(month, day, year):
    if year < 100:
        year += 2000 if year < 50 else 1900
    return f"{MONTHS[month - 1]} {day}, {_spoken_year(year)}"


def _slash_date(match):
    first, second, year = int(match[1]), int(match[2]), int(match[3])
    # Month first unless that's impossible; a page can't say which convention it uses.
    month, day = (second, first) if first > 12 else (first, second)
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return match[0]
    return _spoken_date(month, day, year)


def _iso_date(match):
    year, month, day = int(match[1]), int(match[2]), int(match[3])
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return match[0]
    return _spoken_date(month, day, year)


def _written_date(match):
    return f"{match[1]} {match[2]}, {_spoken_year(int(match[3]))}"


def _time(match):
    hour, minute = int(match[1]), int(match[2])
    if hour > 23 or minute > 59:
        return match[0]
    suffix = f" {match[3][0].upper()} M" if match[3] else ""
    if minute == 0:
        return f"{hour}{suffix}" if suffix else f"{hour} o'clock"
    spoken = f"oh {minute}" if minute < 10 else str(minute)
    return f"{hour} {spoken}{suffix}"


def _money_scale(match):
    unit = CURRENCIES[match[1]][0]
    scale = match[3].lower()
    return f"{match[2]} {MAGNITUDES.get(scale, scale)} {unit}s"


def _money(match):
    unit, small = CURRENCIES[match[1]]
    whole = match[2].replace(",", "")
    words = f"{match[2]} {unit}" + ("" if whole == "1" else "s")
    if not match[3] or int(match[3]) == 0:
        return words
    if int(match[3]) == 1:
        return f"{words} and 1 {small}"
    plural = "pence" if small == "penny" else small + "s"
    return f"{words} and {int(match[3])} {plural}"


NUMBER_FORMS = [
    (re.compile(r"([$€£])(\d[\d,]*(?:\.\d+)?)\s*(thousand|million|billion|trillion|[kKmMbB])\b"), _money_scale),
    (re.compile(r"([$€£])(\d[\d,]*)(?:\.(\d{2}))?(?![\d.]*\d)"), _money),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b"), _slash_date),
    (re.compile(r"\b((?:19|20)\d{2})-(\d{2})-(\d{2})\b"), _iso_date),
    (re.compile(rf"\b({'|'.join(MONTHS)})\s+(\d{{1,2}}),?\s+((?:19|20)\d{{2}})\b"), _written_date),
    (re.compile(r"\b(\d{1,2}):(\d{2})(?::\d{2})?(?:\s*([AaPp])\.?[Mm]\.?)?(?![\d:])"), _time),
]


def spoken_text(text, skip_references=False):
    """What the voice should say for a chunk. The page and the panel keep showing the original text."""
    if skip_references:
        # Saying that a link was there keeps the sentence making sense: "details are at a link".
        text = URL.sub(LINK_WORDS, text)
        for pattern in (NUMBERED_CITATION, AUTHOR_CITATION, YEAR_CITATION):
            text = pattern.sub("", text)
        # A line of nothing but numbers is a leftover page number or table cell.
        if ONLY_NUMBERS.match(text) or not any(c.isalnum() for c in text.replace(LINK_WORDS, "")):
            return ""
    text = PRIVATE_USE.sub(" ", text)
    for pattern, replacement in NUMBER_FORMS:
        text = pattern.sub(replacement, text)
    for pattern, replacement in SPOKEN_WORDS:
        text = pattern.sub(replacement, text)
    text = re.sub(r"\s+[-–—]\s*$", "", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    # The voices are English, so text with no Latin letters or numbers would come out as nonsense.
    return text if any(c.isdigit() or (c.isalpha() and ord(c) < LATIN_END) for c in text) else ""


@dataclass
class Chunk:
    text: str
    page: int
    word: int
    end_page: int
    end_word: int
    rects: dict = field(default_factory=dict)
    heading: bool = False
    spoken: str = ""
    keys: frozenset = frozenset()  # (page, word index) of every word in the chunk


@dataclass
class _Line:
    words: list
    text: str
    y0: float
    y1: float

    @property
    def x0(self):
        return min(w.rect[0] for w in self.words)

    @property
    def x1(self):
        return max(w.rect[2] for w in self.words)


@dataclass
class _Token:
    text: str
    sources: list  # [(page, Word), ...]
    ends_line: bool = False
    list_marker: bool = False


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


def _find_gutters(lines, width):
    """Find empty vertical strips between columns. Lines spanning most of the page don't count."""
    narrow = [line for line in lines if line.x1 - line.x0 < width * WIDE_LINE_SHARE]
    total = sum(line.y1 - line.y0 for line in narrow)
    if total <= 0:
        return []
    coverage = [0.0] * (int(width) + 2)
    for line in narrow:
        height = line.y1 - line.y0
        for x in range(max(0, int(line.x0)), min(len(coverage), int(line.x1) + 1)):
            coverage[x] += height
    first, last = int(width * GUTTER_ZONE[0]), int(width * GUTTER_ZONE[1])
    gutters, start = [], None
    for x in range(first, last + 2):
        empty = x <= last and coverage[x] <= total * GUTTER_MAX_COVERAGE
        if empty and start is None:
            start = x
        elif not empty and start is not None:
            if x - start >= GUTTER_MIN_WIDTH:
                gutters.append((start + x) / 2)
            start = None
    return gutters


def _is_prose_column(lines):
    # Short cells side by side are a table, which reads row by row.
    if len(lines) < COLUMN_MIN_LINES:
        return False
    return statistics.median(len(line.words) for line in lines) >= COLUMN_MIN_WORDS


def reading_order(lines, width):
    """Put multi-column text in the order people read it. Anything else keeps the file's own order."""
    gutters = _find_gutters(lines, width)
    if not gutters:
        return lines
    blocks = {}
    for line in lines:
        blocks.setdefault(line.words[0].block, []).append(line)
    edges = [float("-inf")] + gutters + [float("inf")]
    columns = [[] for _ in range(len(edges) - 1)]
    spanning = []
    def column_of(x0, x1):
        for i in range(len(columns)):
            if edges[i] - 2 <= x0 and x1 <= edges[i + 1] + 2:
                return i
        return None

    for block in blocks.values():
        whole = column_of(min(l.x0 for l in block), max(l.x1 for l in block))
        if whole is not None:
            columns[whole].append(block)
            continue
        # Some files keep lines from both columns in one block, so look at them separately.
        places = [column_of(l.x0, l.x1) for l in block]
        if None in places:
            # A block reaching past its column belongs to the whole page width.
            spanning.append(block)
        else:
            for line, place in zip(block, places):
                columns[place].append([line])
    for column in columns:
        if not _is_prose_column([line for block in column for line in block]):
            return lines
    extents = [(min(b[0].y0 for b in c), max(b[-1].y1 for b in c)) for c in columns]
    for (top_a, bottom_a), (top_b, bottom_b) in zip(extents, extents[1:]):
        overlap = min(bottom_a, bottom_b) - max(top_a, top_b)
        if overlap < 0.5 * min(bottom_a - top_a, bottom_b - top_b):
            return lines
    # Titles, abstracts and wide figures divide the page; columns are read within each band.
    spanning.sort(key=lambda block: block[0].y0)
    ordered, top = [], float("-inf")
    for divider in spanning + [None]:
        bottom = divider[0].y0 if divider else float("inf")
        for column in columns:
            band = [b for b in column if top <= (b[0].y0 + b[-1].y1) / 2 < bottom]
            for block in sorted(band, key=lambda b: b[0].y0):
                ordered.extend(block)
        if divider:
            ordered.extend(divider)
            top = divider[-1].y1
    return ordered


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
    # Without images: on a scanned page, decoding them is most of the time spent here.
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT).get("blocks", []):
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


def _style_at(line, styles):
    first = line.words[0].rect
    cx, cy = (first[0] + first[2]) / 2, (first[1] + first[3]) / 2
    for bbox, bold, size in styles:
        if bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]:
            return bold, size
    return None


def is_contents_page(lines, carried_on=False):
    """A table of contents, either titled as one or carrying on from the page before."""
    if len(lines) < CONTENTS_MIN_LINES:
        return False
    numbered = [m for m in (ENDS_IN_PAGE_NUMBER.search(line.text.strip()) for line in lines) if m]
    if len(numbered) / len(lines) < CONTENTS_SHARE:
        return False
    if carried_on or any(CONTENTS_WORD.search(line.text.strip()) for line in lines):
        return True
    # No title, but page numbers that only ever go up are a contents list. A table's numbers aren't.
    numbers = [int(m[0].strip(" .")) for m in numbered if m[0].strip(" .").isdecimal()]
    rising = sum(b >= a for a, b in zip(numbers, numbers[1:]))
    return len(numbers) >= CONTENTS_MIN_LINES + 1 and rising >= (len(numbers) - 1) * CONTENTS_RISING_SHARE


def _is_heading(line, styles, body, bold_share, next_line=None):
    if len(line.text) > HEADING_MAX_CHARS or not any(c.isalpha() for c in line.text):
        return False
    # Emphasized text in a sentence isn't a title: a title doesn't start in lowercase or run on into one.
    if line.text.lstrip("\"'“‘([")[:1].islower():
        return False
    if next_line is not None and next_line.words[0].block == line.words[0].block and next_line.text.lstrip("\"'“‘([")[:1].islower():
        return False
    # Amounts in a bold table row are data.
    if sum(c.isdigit() for c in line.text) > sum(c.isalpha() for c in line.text) * 0.2:
        return False
    style = _style_at(line, styles)
    if style is None:
        return False
    bold, size = style
    large = body and size >= body * HEADING_SIZE_RATIO
    # On a mostly bold page, bold doesn't say anything about structure.
    return large or (bold and bold_share < 0.5)


def _is_footnote(line, styles, body, height):
    if line.y0 < height * FOOTNOTE_ZONE or not body:
        return False
    style = _style_at(line, styles)
    return style is not None and style[1] <= body * FOOTNOTE_SIZE_RATIO


def _is_table_row(cells):
    """Several short pieces of text side by side, spaced well apart."""
    if len(cells) < 2 or any(len(cell.words) > TABLE_CELL_WORDS for cell in cells):
        return False
    ordered = sorted(cells, key=lambda cell: cell.x0)
    return all(right.x0 - left.x1 >= TABLE_CELL_GAP for left, right in zip(ordered, ordered[1:]))


def _ends_sentence(text, next_text=None):
    if not SENTENCE_END.search(text):
        return False
    bare = text.rstrip("\"'”’)]")
    if bare.lower() in ABBREVIATIONS or INITIAL.match(bare):
        return False
    if ACRONYM.match(bare):
        return next_text is None or next_text.lstrip("\"'“‘([") in SENTENCE_STARTERS
    return True


def _starts_sentence(text):
    first = text.lstrip("\"'“‘([")[:1]
    return first.isupper() or first.isdigit()


class ChunkBuilder:
    """Feed pages in order. Sentences carry across page breaks until they end."""

    def __init__(self, document, furniture=frozenset(), skip_references=False):
        self.document = document
        self.furniture = furniture
        self.skip_references = skip_references
        self.chunks = []
        self._tokens = []
        self._in_references = False
        self._in_contents = False

    def feed(self, index, first_word=0, last_word=None):
        page = self.document.page(index)
        height = page.rect.height
        heading = []
        previous_block = None
        row = []
        lines = [
            line
            for line in page_lines(self.document, index)
            if not (_in_margin(line, height) and (PAGE_NUMBER.match(line.text.strip()) or _furniture_key(line.text) in self.furniture))
        ]
        if not lines:
            return
        if self.skip_references and first_word == 0 and last_word is None:
            self._in_contents = is_contents_page(lines, self._in_contents)
            if self._in_contents:
                return
        styles, body, bold_share = _page_styles(page)
        ordered = reading_order(lines, page.rect.width)
        for position, line in enumerate(ordered):
            if line.words[-1].index < first_word or (last_word is not None and line.words[0].index > last_word):
                continue
            words = [w for w in line.words if w.index >= first_word and (last_word is None or w.index <= last_word)]
            following = ordered[position + 1] if position + 1 < len(ordered) else None
            if _is_heading(line, styles, body, bold_share, following):
                if heading and heading[-1].block != words[0].block:
                    self._emit_heading(index, heading)
                    heading = []
                heading.extend(words)
                continue
            if heading:
                self._emit_heading(index, heading)
                heading = []
            if self.skip_references and (self._in_references or _is_footnote(line, styles, body, height)):
                continue
            block = words[0].block
            if previous_block is not None and block != previous_block and self._tokens:
                if _ends_sentence(self._tokens[-1].text):
                    self._flush()
            previous_block = block
            if row and abs(line.y0 - row[0].y0) > ROW_TOLERANCE:
                # Tables read one row at a time.
                if _is_table_row(row):
                    self._flush()
                row = []
            row.append(line)
            self._add_line(index, words)
        if _is_table_row(row):
            self._flush()
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
            if all(c in BULLETS or PRIVATE_USE.match(c) for c in text):
                self._flush()
                continue
            text = text.lstrip("".join(BULLETS)) or text
            if position == 0 and self._merge_hyphenated(text, index, word):
                continue
            marker = position == 0 and len(words) > 1 and bool(LIST_MARKER.match(text))
            previous = self._tokens[-1] if self._tokens else None
            if marker:
                self._flush()
            elif previous and not previous.list_marker and _ends_sentence(previous.text, text) and _starts_sentence(text):
                self._flush(respect_minimum=True)
            self._tokens.append(_Token(text, [(index, word)], list_marker=marker))
            self._split_if_long()
        if self._tokens:
            self._tokens[-1].ends_line = True

    def _merge_hyphenated(self, text, index, word):
        """Rejoin 'bet-' + 'ween' from printed line wrapping; leave '32-bit' alone."""
        if not self._tokens:
            return False
        previous = self._tokens[-1]
        if previous.ends_line and re.search(r"\w-$", previous.text) and text[:1].isdigit():
            # A name or number broken after its own hyphen, like "gpt-4-" and "0125".
            previous.text += text
            previous.sources.append((index, word))
            previous.ends_line = False
            return True
        if previous.ends_line and re.search(r"[A-Za-z]{2}-$", previous.text) and re.match(r"[a-z]{2}", text):
            keep_hyphen = previous.text[:-1].lower() in COMPOUND_PREFIXES
            previous.text = (previous.text if keep_hyphen else previous.text[:-1]) + text
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
        text = " ".join(w.text for w in words)
        if self.skip_references:
            self._in_references = bool(REFERENCE_HEADING.match(text.strip()))
            if self._in_references:
                return
        self._emit([_Token(w.text, [(index, w)]) for w in words if w.text.strip()], True)

    def _emit(self, tokens, heading):
        text = " ".join(t.text for t in tokens).strip()
        if not any(c.isalnum() for c in text):
            return
        if heading and text[-1] not in ".!?:":
            text += "."
        spoken = spoken_text(text, self.skip_references)
        # A sentence that was nothing but a citation or a link leaves nothing to say.
        if not spoken:
            return
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
                spoken=spoken,
                keys=frozenset((page, word.index) for page, word in sources),
            )
        )


def first_chunk_at(chunks, page, word):
    """Index of the chunk that holds a word, or the next one after it. None if that isn't built yet.

    Word numbers follow the file's order, which isn't always reading order, so chunks can't be
    compared by number alone.
    """
    target = (page, word)
    for i, chunk in enumerate(chunks):
        if target in chunk.keys:
            return i
    # The word produced no chunk, such as a page number, or it's still being built.
    if not any(chunk.page > page for chunk in chunks):
        return None
    for i, chunk in enumerate(chunks):
        if chunk.page > page or (chunk.page == page and chunk.word >= word):
            return i
    return None

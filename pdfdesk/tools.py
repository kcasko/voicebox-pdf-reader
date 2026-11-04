import os
import re

import pymupdf


def parse_ranges(text, page_count):
    """Turn '1-3, 5' into [[0, 1, 2], [4]]. Page numbers are 1-based."""
    groups = []
    for part in re.split(r"[,;\s]+", text.strip()):
        if not part:
            continue
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not match:
            raise ValueError(f'"{part}" is not a page or a range like 2-5.')
        first = int(match.group(1))
        last = int(match.group(2) or first)
        if first < 1 or last > page_count or first > last:
            raise ValueError(f'"{part}" is outside pages 1-{page_count}.')
        groups.append(list(range(first - 1, last)))
    if not groups:
        raise ValueError("Enter at least one page or range.")
    return groups


def merge_files(paths, out_path):
    with pymupdf.open() as merged:
        for path in paths:
            with pymupdf.open(path) as source:
                merged.insert_pdf(source)
        merged.save(out_path, garbage=3, deflate=True)


def save_pages(document, indexes, out_path):
    with pymupdf.open() as target:
        for index in indexes:
            target.insert_pdf(document.doc, from_page=index, to_page=index)
        target.save(out_path, garbage=3, deflate=True)


def split_ranges(document, groups, folder, stem):
    paths = []
    for group in groups:
        label = f"{group[0] + 1}" if len(group) == 1 else f"{group[0] + 1}-{group[-1] + 1}"
        path = os.path.join(folder, f"{stem} - pages {label}.pdf")
        save_pages(document, group, path)
        paths.append(path)
    return paths


def split_every(document, size, folder, stem):
    groups = [list(range(i, min(i + size, len(document)))) for i in range(0, len(document), size)]
    return split_ranges(document, groups, folder, stem)


def compress(document, out_path, image_dpi=150, quality=70):
    """Save a smaller copy; the open document is left as it is."""
    with pymupdf.open("pdf", document.doc.tobytes()) as copy:
        copy.rewrite_images(dpi_threshold=image_dpi + 30, dpi_target=image_dpi, quality=quality)
        copy.subset_fonts()
        copy.save(out_path, garbage=4, deflate=True, clean=True)
    return os.path.getsize(out_path)


def _insert_display_text(page, x, y, text, fontsize, color, opacity=1.0, angle=0):
    # x and y are in on-screen coordinates, so the text stays upright on rotated pages.
    point = pymupdf.Point(x, y) * page.derotation_matrix
    matrix = pymupdf.Matrix(page.rotation + angle)
    page.insert_text(
        point,
        text,
        fontsize=fontsize,
        color=color,
        fill_opacity=opacity,
        morph=(point, matrix),
        overlay=True,
    )


def add_page_numbers(document, template="{page} / {total}", fontsize=10):
    total = len(document)
    with document.edit():
        for index in range(total):
            page = document.doc[index]
            text = template.format(page=index + 1, total=total)
            width = pymupdf.get_text_length(text, fontsize=fontsize)
            rect = page.rect
            _insert_display_text(
                page, (rect.width - width) / 2, rect.height - 24, text, fontsize, (0.25, 0.25, 0.25)
            )


def add_watermark(document, text, fontsize=54, opacity=0.18):
    with document.edit():
        for index in range(len(document)):
            page = document.doc[index]
            rect = page.rect
            width = pymupdf.get_text_length(text, fontsize=fontsize)
            # Offset the baseline so the diagonal text is centered on the page.
            offset = width / 2 * 0.7071
            _insert_display_text(
                page,
                rect.width / 2 - offset,
                rect.height / 2 + offset,
                text,
                fontsize,
                (0.6, 0.1, 0.1),
                opacity=opacity,
                angle=45,
            )


def export_images(document, folder, stem, dpi=150, indexes=None):
    paths = []
    for index in indexes if indexes is not None else range(len(document)):
        path = os.path.join(folder, f"{stem}-{index + 1:04d}.png")
        document.doc[index].get_pixmap(dpi=dpi).save(path)
        paths.append(path)
    return paths


def export_text(document, out_path):
    with open(out_path, "w", encoding="utf-8") as f:
        for index in range(len(document)):
            f.write(document.doc[index].get_text("text"))
            f.write("\n\f\n")

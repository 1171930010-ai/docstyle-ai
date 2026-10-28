"""Local PDF publication-layout evidence, never an automatic submission template.

pdfplumber supplies glyphs and geometry; PDFium supplies the displayed page image.
Each native operation runs in a fresh process, with a wall deadline and Unix CPU
limit. No document text is interpreted as an instruction or sent to a service.
"""
from collections import Counter, defaultdict
import hashlib
import io
import json
import math
import multiprocessing
from importlib.metadata import PackageNotFoundError, version
import re
import shutil
import statistics
import sys
import threading

COORDINATE_SYSTEM = "top-left PDF points, displayed rotation"
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PAGES = 40
MAX_PAGE_CHARACTERS = 15000
MAX_TOTAL_CHARACTERS = 100000
MAX_GRAPHICS = 1500
MAX_PAGE_POINTS = 14400
MAX_RENDER_PIXELS = 12_000_000
OPERATION_TIMEOUT_SECONDS = 35
RENDER_SCALE = 1.5  # 108 dpi. UI scales the same coordinate bbox by this factor.
_PROCESS_SLOTS = threading.BoundedSemaphore(2)

_ALIASES = {
    "TimesNewRomanPSMT": "Times New Roman",
    "TimesNewRomanPS-BoldMT": "Times New Roman",
    "TimesNewRomanPS-ItalicMT": "Times New Roman",
    "TimesNewRomanPS-BoldItalicMT": "Times New Roman",
    "ArialMT": "Arial", "Arial-BoldMT": "Arial",
    "Arial-ItalicMT": "Arial", "Arial-BoldItalicMT": "Arial",
    "Calibri-Bold": "Calibri", "Calibri-Italic": "Calibri",
    "SimSun": "宋体", "SimHei": "黑体",
}


def normalize_font(raw):
    """Strip a documented subset prefix and exact known aliases; never fuzzy match.

    Base14 Times-Roman and Helvetica remain their own families. Name normalization
    does not prove that a local font is installed or that the outlines are equal.
    """
    raw = str(raw or "unknown")
    base = re.sub(r"^[A-Z]{6}\+", "", raw)
    known = base.lower() not in {"unknown", "none", "", "null"}
    normalized = _ALIASES.get(base, base) if known else None
    methods = []
    if base != raw:
        methods.append("subset_prefix_removed")
    if base in _ALIASES:
        methods.append("exact_postscript_alias")
    return {"raw": raw, "base": base, "normalized": normalized,
            "normalization": methods or ["unchanged"], "known": known,
            "bold": bool(re.search(r"bold|heiti|simhei", base, re.I)),
            "italic": bool(re.search(r"italic|oblique", base, re.I)),
            "installed": None}


def _finite(value, default=0.0):
    try:
        value = float(value)
        return round(value, 4) if math.isfinite(value) else default
    except (ValueError, TypeError):
        return default


def _bbox(obj, origin=(0, 0)):
    return [_finite(obj.get("x0", 0) - origin[0]), _finite(obj.get("top", 0) - origin[1]),
            _finite(obj.get("x1", 0) - origin[0]), _finite(obj.get("bottom", 0) - origin[1])]


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _metadata(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("PDF metadata must be a JSON object")
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode()) > 10000:
        raise ValueError("PDF metadata exceeds 10 KB")
    return json.loads(encoded)


def _ocr_status():
    executable = shutil.which("tesseract")
    # Installed executable detection is not language-pack or end-to-end OCR proof.
    return {"available": bool(executable), "used": False,
            "engine": "tesseract" if executable else None,
            "configuration": "detected_not_configured" if executable else "unavailable",
            "languagePacksVerified": False,
            "reason": "OCR is not executed by this local layout extractor. Raster pages require a configured OCR workflow and manual review."}


def _check_data(data):
    if not isinstance(data, bytes):
        raise ValueError("PDF input must be bytes")
    if not data or len(data) > MAX_PDF_BYTES:
        raise ValueError("PDF must be nonempty and no larger than 25 MB")
    if b"%PDF-" not in data[:1024]:
        raise ValueError("Input does not have a PDF header")


def _worker(connection, operation, data, page):
    try:
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (30, 31))
            if sys.platform.startswith("linux"):
                resource.setrlimit(resource.RLIMIT_AS, (1024 ** 3, 1024 ** 3))
        except (ImportError, ValueError, OSError):
            pass
        # Malformed font dictionaries can emit input-derived log text. Evidence is
        # returned in structured results; native parser logs are suppressed.
        import logging
        logging.getLogger("pdfminer").setLevel(logging.CRITICAL)
        result = _extract(data) if operation == "extract" else _render(data, page)
        try:
            connection.send((True, result))
        except (BrokenPipeError, EOFError):
            pass  # Parent has cancelled a timed-out worker.
    except Exception as exc:
        safe_errors = {"PDFPasswordIncorrect": "Encrypted PDF requires a password; password import is unsupported.",
                       "PDFSyntaxError": "Malformed PDF could not be parsed.",
                       "PDFEncryptionError": "Encrypted PDF is unsupported."}
        message = safe_errors.get(type(exc).__name__, str(exc))
        try:
            connection.send((False, message[:500] or type(exc).__name__))
        except (BrokenPipeError, EOFError):
            pass
    finally:
        connection.close()


def _spawn_operation(operation, data, page=None):
    # spawn avoids inheriting a PDFium native state from a multithreaded server.
    # PDFium is only used by one operation in each isolated worker process.
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(sender, operation, data, page), daemon=True)
    try:
        process.start()
        sender.close()
        if not receiver.poll(OPERATION_TIMEOUT_SECONDS):
            raise ValueError("PDF operation exceeded the bounded time/resource limit")
        try:
            ok, result = receiver.recv()
        except EOFError:
            raise ValueError("PDF worker stopped at a native parsing/resource limit") from None
        if not ok:
            raise ValueError(result)
        return result
    finally:
        sender.close()
        receiver.close()
        if process.pid is not None:
            process.join(timeout=.3)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)


def _bounded_operation(operation, data, page=None):
    if not _PROCESS_SLOTS.acquire(timeout=OPERATION_TIMEOUT_SECONDS):
        raise ValueError("PDF workers are busy; bounded operation queue exceeded its time limit")
    try:
        return _spawn_operation(operation, data, page)
    finally:
        _PROCESS_SLOTS.release()


def _dependencies():
    dependencies = {}
    for package in ("pdfplumber", "pdfminer.six", "pypdfium2", "Pillow"):
        try:
            dependencies[package] = version(package)
        except PackageNotFoundError:
            dependencies[package] = None
    return dependencies


def _line_from_chars(chars, orientation):
    font_counts = Counter(c["fontName"] for c in chars if c["text"].strip())
    size_counts = Counter(round(c["size"], 2) for c in chars if c["text"].strip())
    text = "".join(c["text"] for c in chars).strip()
    baseline = statistics.median(c["baseline"][1 if orientation == "horizontal" else 0] for c in chars)
    return {"text": text, "bbox": _union([c["bbox"] for c in chars]),
            "fontNames": list(font_counts), "size": size_counts.most_common(1)[0][0] if size_counts else None,
            "orientation": orientation, "baseline": _finite(baseline),
            "characterIds": [c["id"] for c in chars], "role": "body", "region": "body",
            "column": 1, "inferred": True, "roleConfidence": .5}


def _group_lines(chars):
    groups = defaultdict(list)
    # Median glyph geometry gives stable horizontal rows and vertical columns.
    for char in chars:
        axis = char["baseline"][1] if char["upright"] else char["baseline"][0]
        key = ("horizontal" if char["upright"] else "vertical", round(axis / 2))
        groups[key].append(char)
    lines = []
    for (orientation, _), group in groups.items():
        axis = 0 if orientation == "horizontal" else 1
        reverse = group[0]["matrix"][0] < 0 if orientation == "horizontal" else group[0]["matrix"][1] > 0
        group.sort(key=lambda c: c["bbox"][axis], reverse=reverse)
        segments, segment = [], []
        for char in group:
            gap = (segment[-1]["bbox"][axis] - char["bbox"][axis + 2] if reverse else char["bbox"][axis] - segment[-1]["bbox"][axis + 2]) if segment else 0
            if segment and gap > max(20, 2.5 * char["size"]):
                segments.append(segment)
                segment = []
            segment.append(char)
        if segment:
            segments.append(segment)
        lines.extend(_line_from_chars(segment, orientation) for segment in segments if any(c["text"].strip() for c in segment))
    lines.sort(key=lambda line: (line["bbox"][1], line["bbox"][0]))
    for index, line in enumerate(lines):
        line["id"] = f"l{index + 1}"
    return lines


def _column_count(lines, width, height):
    samples = [line for line in lines if line["orientation"] == "horizontal" and line["region"] == "body"
               and height * .13 < line["bbox"][1] < height * .9]
    left = [line for line in samples if line["bbox"][0] < width * .35 and line["bbox"][2] < width * .55]
    right = [line for line in samples if line["bbox"][0] > width * .48]
    if len(left) >= 4 and len(right) >= 4:
        overlapping = min(max(l["bbox"][3] for l in left), max(l["bbox"][3] for l in right)) - max(min(l["bbox"][1] for l in left), min(l["bbox"][1] for l in right))
        if overlapping > height * .1:
            return 2
    return 1


def _extract(data):
    import pdfplumber
    import pypdfium2
    pages, warnings = [], []
    with pdfplumber.open(io.BytesIO(data)) as document, pypdfium2.PdfDocument(data) as display:
        if not 1 <= len(document.pages) <= MAX_PAGES:
            raise ValueError(f"PDF must contain between 1 and {MAX_PAGES} pages; split larger references first")
        if len(document.pages) != len(display):
            raise ValueError("PDF parser and renderer disagree on the page count")
        total_chars = 0
        for index, original in enumerate(document.pages):
            crop = original.cropbox
            use_crop = crop and crop != original.bbox and all(math.isfinite(float(v)) for v in crop)
            page = original.crop(crop) if use_crop else original
            origin = (page.bbox[0], page.bbox[1])
            width, height = _finite(page.width), _finite(page.height)
            if not 0 < width <= MAX_PAGE_POINTS or not 0 < height <= MAX_PAGE_POINTS:
                raise ValueError("PDF page dimensions exceed supported resource limits")
            renderer_page = display[index]
            try:
                display_width, display_height = renderer_page.get_size()
            finally:
                renderer_page.close()
            if abs(display_width - width) > .5 or abs(display_height - height) > .5:
                raise ValueError("PDF crop/rotation geometry differs between extractor and renderer; evidence cannot be aligned safely")
            raw_chars = page.chars
            total_chars += len(raw_chars)
            if len(raw_chars) > MAX_PAGE_CHARACTERS or total_chars > MAX_TOTAL_CHARACTERS:
                raise ValueError("PDF character count exceeds bounded extraction limits; split the PDF")
            chars = []
            for char_index, char in enumerate(raw_chars):
                matrix = char.get("matrix", (1, 0, 0, 1, char["x0"], height - char["bottom"]))
                upright = bool(char.get("upright", True))
                # pdfminer reports transformed bbox height as size for horizontal
                # writing; a quarter-turn makes that the glyph advance. For an
                # axis-aligned 90/270 degree glyph use its cross-axis extent.
                quarter_turn = abs(float(matrix[0])) < .001 and abs(float(matrix[3])) < .001
                axis_aligned = abs(float(matrix[1])) < .001 and abs(float(matrix[2])) < .001
                size = _finite(char.get("width") if quarter_turn else char.get("size"))
                box = _bbox(char, origin)
                chars.append({"id": f"c{char_index + 1}", "text": str(char.get("text", "")),
                              "bbox": box, "fontName": str(char.get("fontname", "unknown")),
                              "font": normalize_font(char.get("fontname")), "size": size,
                              "rawExtractorSize": _finite(char.get("size")),
                              "sizeMethod": "quarter_turn_cross_axis_extent" if quarter_turn else "pdfminer_glyph_size",
                              "sizeReliable": bool(axis_aligned or quarter_turn),
                              "geometryReliable": bool(box[2] > box[0] and box[3] > box[1]),
                              "upright": upright, "matrix": [_finite(v) for v in matrix],
                              "baseline": [_finite(matrix[4] - origin[0]), _finite(original.height - matrix[5] - origin[1])]})
            char_text = "".join(char["text"] for char in chars)
            nonspace = [ch for ch in char_text if not ch.isspace()]
            bad = sum(ch == "\ufffd" or (ord(ch) < 32 and ch not in "\n\r\t") for ch in nonspace)
            readable = (len(nonspace) - bad) / max(1, len(nonspace))
            useful = len(nonspace) >= 12 and readable >= .8
            quality = {"status": "suitable" if useful else ("absent" if not nonspace else "poor"),
                       "characterCount": len(chars), "nonWhitespaceCount": len(nonspace),
                       "readableRatio": round(readable, 4), "suitableForLayoutInference": useful,
                       "method": "heuristic_text_layer_check", "verifiedOcrAccuracy": None}
            images = [{"bbox": _bbox(obj, origin), "width": _finite(obj.get("width")), "height": _finite(obj.get("height")),
                       "sourceSize": list(obj.get("srcsize", ())), "name": str(obj.get("name", ""))[:100]}
                      for obj in page.images[:MAX_GRAPHICS]]
            graphic_lines = list(page.lines) + list(page.rect_edges)
            if len(graphic_lines) > MAX_GRAPHICS:
                raise ValueError("PDF vector line count exceeds bounded table-detection limits")
            edges = [{"bbox": _bbox(edge, origin), "widthPt": _finite(edge.get("linewidth")),
                      "kind": edge.get("object_type", "line")} for edge in graphic_lines]
            tables = []
            if useful and len(graphic_lines) <= 400:
                for table in page.find_tables()[:30]:
                    table_box = [table.bbox[0] - origin[0], table.bbox[1] - origin[1], table.bbox[2] - origin[0], table.bbox[3] - origin[1]]
                    cells = [[cell[0] - origin[0], cell[1] - origin[1], cell[2] - origin[0], cell[3] - origin[1]] for cell in table.cells[:3000]]
                    tables.append({"bbox": [_finite(v) for v in table_box], "cells": cells,
                                   "method": "pdfplumber_vector_intersections", "status": "candidate", "confidence": .7})
            lines = _group_lines(chars) if useful else []
            for line in lines:
                for table in tables:
                    x, y = (line["bbox"][0] + line["bbox"][2]) / 2, (line["bbox"][1] + line["bbox"][3]) / 2
                    box = table["bbox"]
                    if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                        line["region"] = "table"
                if line["region"] == "body":
                    for image in images:
                        box = image["bbox"]
                        x, y = (line["bbox"][0] + line["bbox"][2]) / 2, (line["bbox"][1] + line["bbox"][3]) / 2
                        if (box[2] - box[0]) * (box[3] - box[1]) < width * height * .6 and box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                            line["region"] = "figure_text"
                if line["region"] == "body" and len(line["text"]) < 80 and re.search(r"[=∑∫]", line["text"]) and line["bbox"][0] > width * .15:
                    line["region"] = "equation"
                if re.fullmatch(r"\(?\d+\)?", line["text"]) and line["bbox"][0] > width * .7 and height * .08 < line["bbox"][1] < height * .9:
                    line["region"] = "equation_number"
            fonts = [normalize_font(font) for font in sorted({char["fontName"] for char in chars})]
            if any(not font["known"] for font in fonts):
                warnings.append(f"Page {index + 1}: missing font information; font names remain unknown.")
            if any(not char["geometryReliable"] and char["text"].strip() for char in chars):
                warnings.append(f"Page {index + 1}: incomplete glyph metrics; degenerate evidence boxes are retained as unknown geometry, not expanded into fabricated coordinates.")
            if any(not char["sizeReliable"] for char in chars):
                warnings.append(f"Page {index + 1}: arbitrary-angle glyph transforms cannot establish a reliable font size; affected measurements remain unknown candidates.")
            if not useful:
                warnings.append(f"Page {index + 1}: text layer is {quality['status']}; needs OCR/manual review. No layout rules inferred from this page.")
            pages.append({"number": index + 1, "width": width, "height": height,
                          "rotation": int(original.rotation or 0) % 360, "coordinateSystem": COORDINATE_SYSTEM,
                          "cropOrigin": list(origin), "textQuality": quality, "characters": chars,
                          "fontNames": fonts, "images": images, "tableCandidates": tables,
                          "lineCandidates": edges, "lines": lines, "regions": [], "columns": 1,
                          "pageRole": "first" if index == 0 else "body", "pageRoleInferred": True,
                          "observations": {"baselineDistancesPt": [], "wordSpacingUnknown": True,
                                           "dimensions": {"width": width, "height": height, "unit": "pt", "measured": True}}})
            original.close()
    _classify_pages(pages)
    return {"pages": pages, "warnings": warnings}


def _classify_pages(pages):
    repeating = Counter()
    for page in pages:
        seen = set()
        for line in page["lines"]:
            if line["bbox"][1] < page["height"] * .07 or line["bbox"][3] > page["height"] * .93:
                seen.add(re.sub(r"\d+", "#", line["text"]).lower())
        repeating.update(seen)
    reference_mode = False
    for page in pages:
        ordinary = [line for line in page["lines"] if line["region"] == "body" and line["size"]]
        size_mode = Counter(line["size"] for line in ordinary).most_common(1)
        body_size = size_mode[0][0] if size_mode else 11
        max_size = max((line["size"] for line in ordinary), default=body_size)
        for line in page["lines"]:
            text = line["text"]
            normalized = re.sub(r"\d+", "#", text).lower()
            top, bottom = line["bbox"][1], line["bbox"][3]
            if (repeating[normalized] >= 2 or (len(pages) == 1 and line["size"] <= 9)) and top < page["height"] * .07:
                line["region"] = "header"
                line["role"] = "note"
                continue
            if bottom > page["height"] * .93 and (repeating[normalized] >= 2 or re.fullmatch(r"\d+", text)):
                line["region"] = "footer"
                line["role"] = "note"
                continue
            if line["region"] in {"table", "equation", "equation_number", "figure_text"}:
                continue
            if re.match(r"^(References|Bibliography|参考文献)\b", text, re.I):
                reference_mode = True
                page["pageRole"] = "references"
                line["role"] = "heading1"
                line["roleConfidence"] = .8
            elif reference_mode:
                line["role"] = "reference"
                page["pageRole"] = "references"
                line["roleConfidence"] = .75
            elif re.match(r"^(Abstract|摘要)\s*[:：]?", text, re.I):
                line["role"] = "abstract"
                line["roleConfidence"] = .8
            elif re.match(r"^(Keywords?|关键词)\s*[:：]?", text, re.I):
                line["role"] = "keywords"
                line["roleConfidence"] = .8
            elif re.match(r"^(Author|作者)\s*[:：]", text, re.I):
                line["role"] = "author"
                line["roleConfidence"] = .75
            elif re.match(r"^(Table|Figure|Fig\.?|图|表)\s*\d", text, re.I):
                line["role"] = "caption"
                line["roleConfidence"] = .75
            elif re.match(r"^(Note|Source|注|资料来源)\s*[:：]", text, re.I):
                line["role"] = "note"
                line["roleConfidence"] = .75
            elif top > page["height"] * .75 and line["size"] < body_size * .85 and re.match(r"^[\d①②③④⑤⑥⑦⑧⑨*†]", text):
                line["role"] = "note"
                line["region"] = "footnote"
                line["roleConfidence"] = .4
            elif page["number"] == 1 and line["size"] == max_size and (max_size > body_size * 1.25 or (max_size >= 16 and top < page["height"] * .22)):
                line["role"] = "title"
                line["roleConfidence"] = .6
            elif re.match(r"^\d+(?:\.\d+){0,8}\s+\D", text) and len(text) < 100 and line["size"] > body_size * 1.1:
                numbering = re.match(r"^(\d+(?:\.\d+)*)", text)[1]
                line["role"] = f"heading{min(numbering.count('.') + 1, 9)}"
                line["roleConfidence"] = .6
        page["columns"] = _column_count(page["lines"], page["width"], page["height"])
        if page["columns"] == 2:
            for line in page["lines"]:
                if line["role"] == "title" or line["bbox"][0] < page["width"] * .4 < line["bbox"][2]:
                    line["column"] = 0
                else:
                    line["column"] = 2 if line["bbox"][0] > page["width"] * .48 else 1
        by_column = defaultdict(list)
        for line in page["lines"]:
            if line["role"] == "body" and line["region"] == "body":
                by_column[(line["column"], line["orientation"])].append(line)
        distances = []
        for lines in by_column.values():
            baselines = sorted({line["baseline"] for line in lines})
            distances.extend(_finite(b - a) for a, b in zip(baselines, baselines[1:]) if .1 < b - a < 100)
        page["observations"]["baselineDistancesPt"] = distances[:100]
        page["observations"]["columns"] = {"value": page["columns"], "inferred": True, "method": "separated_line_extents", "confidence": .65 if page["columns"] == 2 else .5}
        page["regions"] = [{"id": line["id"], "bbox": line["bbox"], "text": line["text"],
                            "role": line["role"], "kind": line["region"], "fontNames": line["fontNames"],
                            "size": line["size"], "column": line["column"], "inferred": True} for line in page["lines"]]


def _make_candidates(pages, source_hash):
    candidates, warnings, groups = [], [], defaultdict(list)
    for page in pages:
        char_map = {char["id"]: char for char in page["characters"]}
        for line in page["lines"]:
            if line["region"] not in {"body", "table", "footnote"}:
                continue
            target = "table" if line["region"] == "table" else "style"
            for char_id in line["characterIds"]:
                char = char_map[char_id]
                if char["text"].strip():
                    groups[(target, line["role"], char["fontName"], round(char["size"], 2))].append((page, line, char))

    def add(target, role, field, value, unit, page, line, measurement, confidence, state="set", method="pdfplumber_glyph_measurement"):
        index = len(candidates) + 1
        candidates.append({"id": f"pdf-{source_hash[:12]}-{index}", "target": target,
                           "role": role, "field": field, "state": state, "value": value,
                           "unit": unit, "status": "pending", "confidence": round(confidence, 3),
                           "confidenceMeaning": "heuristic evidence/role score, not measured accuracy",
                           "source": {"kind": "pdf_publication", "pdfHash": source_hash,
                                      "page": page["number"], "bbox": line["bbox"], "method": method,
                                      "evidence": line["text"][:500], "measurement": measurement,
                                      "coordinateSystem": COORDINATE_SYSTEM,
                                      "pageRole": page["pageRole"], "publicationNotSubmission": True}})

    role_sizes = defaultdict(set)
    # Separate observation clusters; do not silently average conflicting samples.
    for (target, role, raw_font, size), samples in list(groups.items())[:150]:
        page, line, char = samples[0]
        role_sizes[(target, role)].add(size)
        info = normalize_font(raw_font)
        evidence_confidence = min(.85, line["roleConfidence"] + .1)
        reliable = all(sample[2]["sizeReliable"] and sample[2]["geometryReliable"] for sample in samples)
        add(target, role, "size", size if reliable and 1 <= size <= 200 else None, "pt", page, line,
            {"value": size, "unit": "pt", "measured": reliable,
             "samples": [sample[2]["size"] for sample in samples[:50]],
             "glyphBboxes": [sample[2]["bbox"] for sample in samples[:20]],
             "count": len(samples), "rawExtractorSize": char["rawExtractorSize"], "sizeMethod": char["sizeMethod"]}, evidence_confidence,
            state="set" if reliable and 1 <= size <= 200 else "unspecified")
        usable_name = info["known"] and len(info["normalized"]) <= 100 and not re.search(r"[\x00-\x1f]", info["normalized"])
        font_fields = set()
        if any(re.search(r"[\u3400-\u9fff]", sample[2]["text"]) for sample in samples):
            font_fields.add("font")
        if any(re.search(r"[A-Za-z0-9]", sample[2]["text"]) for sample in samples):
            font_fields.add("latin")
        for field in sorted(font_fields or {"latin"}):
            add(target, role, field, info["normalized"] if usable_name else None, "name", page, line,
                {"rawFontName": raw_font, "normalizedFontName": info["normalized"],
                 "normalization": info["normalization"], "measured": info["known"],
                 "fontInstallationVerified": False, "unit": "name"}, evidence_confidence,
                state="set" if usable_name else "unspecified")
        if target == "style":
            for style in ("bold", "italic"):
                if info[style]:
                    add(target, role, style, True, "bool", page, line,
                        {"rawFontName": raw_font, "value": True, "unit": "bool", "measured": False,
                         "reason": "Style inferred from an explicit PostScript font-name suffix; requires confirmation."}, min(.65, evidence_confidence),
                        method="postscript_style_name_inference")
    for (target, role), sizes in role_sizes.items():
        if len(sizes) > 1:
            warnings.append(f"Layout conflict for {target}/{role} font size: distinct measured values {sorted(sizes)} pt remain separate pending candidates; no averaging.")
    body = next(((page, line) for page in pages for line in page["lines"] if line["role"] == "body" and line["region"] == "body"), None)
    if body:
        page, line = body
        for field, unit in (("line", "multiple"), ("before", "pt"), ("after", "pt"), ("indent", "chars")):
            add("style", "body", field, None, unit, page, line,
                {"value": None, "unit": unit, "measured": False,
                 "observedBaselineDistancesPt": page["observations"]["baselineDistancesPt"],
                 "reason": "PDF glyph positions do not establish Word line mode, paragraph spacing, or first-line indentation parameters."}, .0,
                state="unspecified", method="unknown_word_parameter")
    first = next((page for page in pages if page["textQuality"]["suitableForLayoutInference"]), None)
    if first and first["lines"]:
        w, h = first["width"], first["height"]
        line = {"text": f"Displayed page measures {w} x {h} PDF points.", "bbox": [0, 0, w, h]}
        add("page", "body", "orientation", "portrait" if h >= w else "landscape", "enum", first, line,
            {"width": w, "height": h, "unit": "pt", "measured": True,
             "reason": "Orientation inferred from displayed dimensions; does not establish original authoring settings."}, .75,
            method="displayed_page_dimensions")
        for paper, pw, ph in (("A4", 595.276, 841.89), ("Letter", 612, 792)):
            if (abs(w - pw) < 1 and abs(h - ph) < 1) or (abs(w - ph) < 1 and abs(h - pw) < 1):
                add("page", "body", "paper", paper, "enum", first, line,
                    {"width": w, "height": h, "unit": "pt", "measured": True,
                     "reason": "Matches standard dimensions within 1 pt; publication page size is a candidate only."}, .75,
                    method="standard_page_size_match")
                break
    for page in pages:
        for line in page["lines"]:
            if line["region"] == "equation":
                add("equation", "body", "align", None, "enum", page, line,
                    {"bbox": line["bbox"], "unit": "pt", "measured": True,
                     "reason": "Formula position observed. Word alignment and expression remain unknown; expression is never rewritten."}, .0,
                    state="unspecified", method="heuristic_equation_position")
                break
        for table in page["tableCandidates"]:
            evidence_line = next((line for line in page["lines"] if line["region"] == "table"), None)
            if evidence_line:
                evidence_line = {**evidence_line, "bbox": table["bbox"]}
                add("table", "body", "borderMode", None, "enum", page, evidence_line,
                    {"bbox": table["bbox"], "cellCount": len(table["cells"]), "unit": "pt", "measured": True,
                     "reason": "PDF table lines are observed; Word border configuration, merged cells and table values cannot be reverse-derived safely."}, .0,
                    state="unspecified", method="pdfplumber_vector_intersections")
                box = table["bbox"]
                stroke_sizes = sorted({edge["widthPt"] for edge in page["lineCandidates"]
                                       if box[0] <= edge["bbox"][0] <= edge["bbox"][2] <= box[2]
                                       and box[1] <= edge["bbox"][1] <= edge["bbox"][3] <= box[3]})
                for stroke in stroke_sizes[:10]:
                    add("table", "body", "borderSize", stroke if .25 <= stroke <= 6 else None, "pt", page, evidence_line,
                        {"value": stroke, "unit": "pt", "measured": True,
                         "reason": "Observed PDF vector stroke width; Word table border weight is a pending publication-layout candidate."}, .65,
                        state="set" if .25 <= stroke <= 6 else "unspecified", method="pdfplumber_vector_stroke_width")
                break
    return candidates, warnings


def analyze_pdf(data: bytes, name: str, metadata: dict = None):
    """Analyze an in-memory PDF. All extracted rules require user confirmation."""
    safe_name = re.sub(r"[\x00-\x1f]", "", str(name or "reference.pdf").replace("\\", "/").rsplit("/", 1)[-1])[:200] or "reference.pdf"
    source_hash = hashlib.sha256(data).hexdigest() if isinstance(data, bytes) else None
    result = {"name": safe_name, "sourceHash": source_hash, "metadata": {}, "status": "failed",
              "pages": [], "candidates": [], "warnings": [], "coordinateSystem": COORDINATE_SYSTEM,
              "ocr": _ocr_status(), "inference": "local_heuristic_not_ai", "publicationNotSubmission": True,
              "dependencyVersions": _dependencies(),
              "limits": {"maxBytes": MAX_PDF_BYTES, "maxPages": MAX_PAGES,
                         "maxCharactersPerPage": MAX_PAGE_CHARACTERS,
                         "maxTotalCharacters": MAX_TOTAL_CHARACTERS,
                         "operationTimeoutSeconds": OPERATION_TIMEOUT_SECONDS}}
    try:
        _check_data(data)
        result["metadata"] = _metadata(metadata)
        extracted = _bounded_operation("extract", data)
        result.update(extracted)
        result["candidates"], extra = _make_candidates(result["pages"], source_hash)
        result["warnings"].extend(extra)
        result["status"] = "needs_ocr" if any(not page["textQuality"]["suitableForLayoutInference"] for page in result["pages"]) else "pending_confirmation"
        result["warnings"].append("Publication layout is reference evidence, not official submission guidance. Roles, columns, and template applicability require confirmation.")
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = str(exc)[:500]
        result["warnings"].append(result["error"])
    return result


def _render(data, number):
    import pypdfium2
    with pypdfium2.PdfDocument(data) as document:
        if len(document) > MAX_PAGES:
            raise ValueError(f"PDF exceeds the {MAX_PAGES}-page rendering limit")
        if number > len(document):
            raise ValueError("PDF page number is outside the document")
        page = document[number - 1]
        try:
            width, height = page.get_size()
            if not 0 < width <= MAX_PAGE_POINTS or not 0 < height <= MAX_PAGE_POINTS:
                raise ValueError("PDF page dimensions exceed rendering limits")
            scale = min(RENDER_SCALE, math.sqrt(MAX_RENDER_PIXELS / (width * height)))
            while math.ceil(width * scale) * math.ceil(height * scale) > MAX_RENDER_PIXELS:
                scale *= .999
            bitmap = page.render(scale=scale)
            try:
                image = bitmap.to_pil()
                output = io.BytesIO()
                image.save(output, format="PNG")
                return output.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()


def render_page(data, page):
    """Return a PNG of displayed page `page` (1-based), without executing actions."""
    _check_data(data)
    if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= MAX_PAGES:
        raise ValueError(f"PDF page number must be an integer between 1 and {MAX_PAGES}")
    return _bounded_operation("render", data, page)

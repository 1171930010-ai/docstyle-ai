# PDF subsystem validation

This folder contains eight **self-built synthetic PDFs**, ten persisted PDF pages,
independent authoring ground truth, and locally produced extraction/render evidence.
No real journal PDF was supplied, and no journal learning or AI result is claimed.

## Actual checks

Command: `.venv/bin/python -m unittest test_pdf_reference -v`

Latest observed result: **20 tests passed**, 2.255 seconds, on 2026-10-13 local time.
The suite covers measured title/body/reference sizes and positions; source hashes;
font subset prefixes and exact aliases; missing font information; unknown Word
spacing and indentation; two-column separation; repeated headers/footers; table
cells and vector borders; equation position without expression edits; scan/OCR
status; input size, page-count and wall deadline failures; candidate Schema
validation; preservation of pending-rule state; cross-sample conflicts; bilingual
font fields; figure/footnote exclusions; 0/90/180/270-degree text order and image
evidence; arbitrary-angle unknown size; cropped display coordinates.

Eight fixture PDFs have 7 `pending_confirmation` results and 1 `needs_ocr` result.
The scanned PDF has zero candidate rules. Missing `/BaseFont` remains unknown and
its degenerate raw glyph boxes are warned about, rather than being fabricated.
Additional in-memory self-built test PDFs are generated for specialized cases;
they are not counted among the eight persisted fixtures.

Command: `.venv/bin/python validation/v5/pdf_fixtures/inspect_fixtures.py`

Actual extraction JSON and all ten rendered pages appear under `evidence/`.
`fixture-evidence-grid.png` and `digital-page3-evidence.png` were visually inspected.
Highlight rectangles enclose measured text on digital, column and rotated pages;
the reference page retains its role and separate 9-point measurement.

Runtime versions recorded in results: pdfplumber 0.11.10, pdfminer.six 20260107,
pypdfium2 5.14.0, Pillow 12.3.0. Fixtures are built with ReportLab and Pillow.
Primary dependency documentation consulted:
[pdfplumber](https://github.com/jsvine/pdfplumber) and
[pypdfium2](https://pypdfium2.readthedocs.io/en/stable/python_api.html).

## API and coordinate contract

`analyze_pdf(data: bytes, name: str, metadata: dict = None)` returns JSON-safe
features and pending RuleItems. `render_page(data, page)` returns PNG bytes;
`page` is 1-based. Native operations run in fresh spawned processes; a semaphore
allows at most two native workers in the server process. CPU limit is 30 seconds
on supporting Unix systems and wall timeout is 35 seconds per worker; queue wait
is separately bounded to 35 seconds. Limits are 25 MB, 40 pages, 15,000 glyphs per
page, 100,000 glyphs per document, and 12 million rendered pixels. Linux workers
also impose a 1 GiB address-space limit. Rendering is 108 dpi where within bounds.

`pages[]` contains `number,width,height,rotation,columns,pageRole,textQuality,
characters,lines,regions,fontNames,images,tableCandidates,lineCandidates,observations`.
Coordinates are **top-left PDF points, displayed rotation**, relative to the
displayed CropBox. Character and line `bbox` values are `[x0,y0,x1,y1]`.
`lines[]` carries `bbox,text,fontNames,size,role,region,column`; regions carry
`bbox,text,fontNames,size,role,kind,column`. The UI must scale bbox coordinates by
the rendered image's actual pixel width/page width and height/page height.

## Limits and unverified areas

Roles, columns, footnotes, figure text and table/equation regions use transparent
local heuristics, whose confidence is not measured accuracy. Complex layouts and
OCR-generated text overlays need manual review. Arbitrary-angle glyph transforms
do not produce confirmed font size. A font-name alias does not prove installation
or identical outlines. Positive bold/italic names are inferred pending candidates.

PDF dimensions and glyph/stroke measurements do not establish Word margins,
line-spacing mode, paragraph spacing, first-line indentation, table merge
structure, numerical data, formula expressions or exact publication pagination.
Unknown Word parameters are `state=unspecified,value=null`; differing sizes stay
separate candidates. Page dimensions/column count are observations; matching
standard paper size and orientation are pending inferred candidates.

OCR executable detection is truthful but language packs/configuration and actual
OCR are unverified (`used=false`). Encrypted PDFs need a future password workflow.
The published page geometry is evidence, not official submission guidance. Real
journal validation and the future 30–50-document corpus remain pending.

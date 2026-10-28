# Self-built PDF fixtures

All eight PDFs were authored locally by `build_fixtures.py`. They are synthetic fixtures, not journal articles, learned publisher templates, or AI output. `groundtruth.json` records authoring inputs independently from extraction. Rebuild with `.venv/bin/python validation/v5/pdf_fixtures/build_fixtures.py`.

The missing-font fixture intentionally omits `/BaseFont`. The rotated fixture contains vertical displayed text. The scanned fixture has only a raster image.

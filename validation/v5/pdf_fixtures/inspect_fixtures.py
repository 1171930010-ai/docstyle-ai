"""Produce locally rendered, highlighted evidence and machine-readable summaries."""
import io
import json
from pathlib import Path
import sys
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[2]))
from pdf_reference import analyze_pdf, render_page


def inspect():
    truth = json.loads((ROOT / "groundtruth.json").read_text())
    target = ROOT / "evidence"
    target.mkdir(exist_ok=True)
    summaries, tiles = [], []
    for name in truth["fixtures"]:
        data = (ROOT / name).read_bytes()
        result = analyze_pdf(data, name, {"provenance": "self-built synthetic fixture"})
        (target / f"{Path(name).stem}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        first_raster = None
        for page in result["pages"]:
            number = page["number"]
            raster = Image.open(io.BytesIO(render_page(data, number))).convert("RGB")
            raster.save(target / f"{Path(name).stem}-page{number}.png")
            draw = ImageDraw.Draw(raster)
            scale_x, scale_y = raster.width / page["width"], raster.height / page["height"]
            for item in result["candidates"]:
                if item["source"]["page"] == number and item["field"] == "size":
                    x0, y0, x1, y1 = item["source"]["bbox"]
                    draw.rectangle((x0 * scale_x, y0 * scale_y, x1 * scale_x, y1 * scale_y), outline="red", width=2)
            raster.save(target / f"{Path(name).stem}-page{number}-evidence.png")
            if number == 1:
                first_raster = raster
        raster = first_raster
        raster.thumbnail((300, 390))
        tile = Image.new("RGB", (320, 440), "#eeeeee")
        tile.paste(raster, ((320 - raster.width) // 2, 25))
        label = ImageDraw.Draw(tile)
        label.text((10, 5), name, fill="black")
        label.text((10, 418), result["status"], fill="black")
        tiles.append(tile)
        summaries.append({"name": name, "status": result["status"], "sourceHash": result["sourceHash"],
                          "pages": len(result["pages"]), "candidates": len(result["candidates"]),
                          "ocrUsed": result["ocr"]["used"]})
    grid = Image.new("RGB", (1280, 880), "white")
    for index, tile in enumerate(tiles):
        grid.paste(tile, ((index % 4) * 320, (index // 4) * 440))
    grid.save(target / "fixture-evidence-grid.png")
    (target / "summary.json").write_text(json.dumps({"provenance": truth["provenance"], "fixtureCount": len(summaries), "results": summaries}, indent=2), encoding="utf-8")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    inspect()

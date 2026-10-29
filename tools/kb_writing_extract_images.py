"""Extract embedded images from writing PDFs into an output dir (for review / KB assets).
Usage: python tools/kb_writing_extract_images.py OUTDIR PDF [PDF...]
Skips the 3580x1080 decorative banner image."""
import sys, pathlib, pymupdf
root = pathlib.Path(__file__).resolve().parents[1]
out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
for rel in sys.argv[2:]:
    doc = pymupdf.open(root / rel)
    stem = pathlib.Path(rel).stem.replace(" ", "_")
    for i, page in enumerate(doc):
        for j, im in enumerate(page.get_images(full=True)):
            if (im[2], im[3]) == (3580, 1080):
                continue
            pix = pymupdf.Pixmap(doc, im[0])
            if pix.n - pix.alpha >= 4:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            name = out / f"{stem}_p{i+1}_{j}.png"
            pix.save(name)
            print(name.name, pix.width, pix.height)

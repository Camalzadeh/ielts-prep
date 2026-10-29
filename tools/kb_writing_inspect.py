"""Inspect writing PDFs: list pages with embedded images (for KB asset extraction)."""
import sys, fitz, pathlib
root = pathlib.Path(__file__).resolve().parents[1]
for rel in sys.argv[1:]:
    p = root / rel
    doc = fitz.open(p)
    print("==", rel, "pages:", len(doc))
    for i, page in enumerate(doc):
        imgs = page.get_images(full=True)
        if imgs:
            print(f"  page {i+1}: {len(imgs)} images", [(im[2], im[3]) for im in imgs])

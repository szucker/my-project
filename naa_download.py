#!/usr/bin/env python3
"""Download digitised NAA RecordSearch files page by page and combine each into a PDF.

Usage:
    pip install requests pillow img2pdf
    python naa_download.py 3445411 1339402          # one or more item barcodes
    python naa_download.py --check 3445411          # test page 1 only, download nothing else
    python naa_download.py --pages 42 3445411       # set the page count yourself
    python naa_download.py 217144:138 273513:250    # barcode:pages (N= in the gallery viewer URL)
    python naa_download.py --pdf-only 3445411       # offline: build the PDF from images already in 3445411/

Output, for each barcode:
    {barcode}/{barcode}_{page:03d}.jpg   page images (already-saved pages are skipped, so you can resume)
    {barcode}.pdf                        all pages in order

Politeness: one request at a time, a 1-2 second pause between requests, up to 3 retries
per page. The script never logs in and never tries to get around a block. If the server
sends a challenge page (e.g. Cloudflare) or a non-image, it stops and reports this.

Page count: RecordSearch has no simple public page-count endpoint, so unless you give
--pages, the script requests page 1, 2, 3, ... and stops at the first page that comes back
as a clean "no image" response (after retries). An empty file or one that isn't
digitised fails on page 1, and you are told to request digitisation.
"""
import argparse
import io
import random
import sys
import time
from pathlib import Path

import requests
try:
    import img2pdf  # preferred: lossless JPEG-to-PDF
except ImportError:  # e.g. on iPhone Python apps; fall back to Pillow
    img2pdf = None
from PIL import Image

IMAGE_URL = "https://recordsearch.naa.gov.au/SearchNRetrieve/NAAMedia/ShowImage.aspx?B={barcode}&S={page}&T=P"
HEADERS = {"User-Agent": "Mozilla/5.0 (personal historical research; polite single-threaded downloader)"}
MAX_RETRIES = 3
MAX_PAGES = 2000  # safety stop


class Blocked(Exception):
    """The server refused us (challenge page / 403 / 429). Do not keep hammering it."""


def pause():
    time.sleep(random.uniform(1.0, 2.0))


def fetch_page(session, barcode, page):
    """Return JPEG bytes, or None if the page clearly does not exist.

    Raises Blocked on access refusals, RuntimeError after repeated transient errors.
    """
    url = IMAGE_URL.format(barcode=barcode, page=page)
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=60)
            ctype = r.headers.get("Content-Type", "")
            body_start = r.content[:20000].lower()
            if b"challenge-platform" in body_start or b"attention required" in body_start:
                raise Blocked(f"challenge page from server (HTTP {r.status_code}); open RecordSearch in a "
                              "browser on this network to check, and try again later")
            if r.status_code in (401, 403, 429):
                raise Blocked(f"HTTP {r.status_code} for {url}")
            if r.status_code == 200 and ctype.startswith("image/"):
                img = Image.open(io.BytesIO(r.content))
                img.load()  # checks the image is complete
                if img.format != "JPEG":  # normalise so every page is a JPEG
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, "JPEG", quality=92)
                    return buf.getvalue()
                return r.content
            if r.status_code in (200, 404) and not ctype.startswith("image/"):
                # Past the last page (or not digitised): the server answers with HTML/empty instead of an image.
                last_err = f"no image (HTTP {r.status_code}, {ctype or 'no content type'})"
                if attempt == MAX_RETRIES:
                    return None
            else:
                last_err = f"HTTP {r.status_code}"
        except Blocked:
            raise
        except (requests.RequestException, OSError) as e:  # OSError covers truncated images from PIL
            last_err = repr(e)
        print(f"    page {page}: attempt {attempt} failed ({last_err}); retrying")
        time.sleep(2 * attempt + random.uniform(0, 1))
    raise RuntimeError(last_err)


def process(session, barcode, pages=None, check_only=False):
    folder = Path(barcode)
    folder.mkdir(exist_ok=True)
    saved, failed = [], []
    page = 1
    limit = pages or MAX_PAGES
    print(f"[{barcode}]")
    while page <= limit:
        path = folder / f"{barcode}_{page:03d}.jpg"
        if path.exists() and path.stat().st_size > 0:
            saved.append(path)
            page += 1
            continue
        try:
            data = fetch_page(session, barcode, page)
        except RuntimeError as e:
            print(f"    page {page}: FAILED after {MAX_RETRIES} attempts ({e})")
            failed.append(page)
            if pages is None and len(failed) >= 3 and failed[-3:] == list(range(page - 2, page + 1)):
                print("    three pages in a row failed; stopping this file")
                break
            page += 1
            pause()
            continue
        if data is None:
            if pages is None:
                break  # end of file
            print(f"    page {page}: no image returned")
            failed.append(page)
        else:
            path.write_bytes(data)
            saved.append(path)
            print(f"    page {page}: saved")
        if check_only:
            break
        page += 1
        pause()

    if not saved:
        print(f"    No pages found. Barcode {barcode} may not be digitised, or may be closed / not yet "
              "examined. Check the item in RecordSearch; if it is open but not digitised, you can request "
              "digitisation there.")
        return barcode, 0, failed
    if check_only:
        print(f"    Check OK: page 1 is an image ({saved[0]})")
        return barcode, len(saved), failed

    make_pdf(barcode, saved)
    return barcode, len(saved), failed


def make_pdf(barcode, paths):
    pdf_path = Path(f"{barcode}.pdf")
    files = sorted(paths)
    if img2pdf:
        pdf_path.write_bytes(img2pdf.convert([str(p) for p in files]))
    else:
        imgs = [Image.open(p).convert("RGB") for p in files]
        imgs[0].save(pdf_path, "PDF", save_all=True, append_images=imgs[1:], resolution=200)
    print(f"    wrote {pdf_path} ({len(files)} pages)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("barcodes", nargs="+")
    ap.add_argument("--pages", type=int, help="page count, if you already know it (applies to every barcode given)")
    ap.add_argument("--pdf-only", action="store_true",
                    help="don't download; just combine images already in each barcode folder into a PDF")
    ap.add_argument("--check", action="store_true", help="only fetch page 1 of each barcode to check the URL works")
    args = ap.parse_args()

    if args.pdf_only:
        for bc in (b.partition(":")[0] for b in args.barcodes):
            files = sorted(Path(bc.strip()).glob("*.jpg"))
            if not files:
                print(f"{bc}: no .jpg files found in folder {bc}/")
                continue
            make_pdf(bc.strip(), files)
        return 0

    session = requests.Session()
    results = []
    for i, bc in enumerate(args.barcodes):
        if i:
            pause()
        try:
            code, _, n = bc.strip().partition(":")
            results.append(process(session, code, int(n) if n else args.pages, args.check))
        except Blocked as e:
            print(f"    BLOCKED: {e}\nStopping; nothing more will be requested.")
            results.append((bc, None, []))
            break

    print("\nSummary")
    for bc, n, failed in results:
        status = "blocked" if n is None else f"{n} pages"
        print(f"  {bc}: {status}" + (f"; failed pages: {failed}" if failed else ""))
    return 1 if any(n is None or failed for _, n, failed in results) else 0


if __name__ == "__main__":
    sys.exit(main())

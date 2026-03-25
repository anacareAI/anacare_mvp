"""
download_zip_data.py

Downloads the US Census ZCTA centroid file (free, public domain) and saves it
to tools/data/zcta_centroids.tsv for use by geocode.py.

This only needs to be run once. File is ~2 MB.

Usage:
    python tools/download_zip_data.py
"""

import logging
import sys
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Census ZCTA 2020 Gazetteer file (tab-separated)
# https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html
CENSUS_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2020_Gazetteer/2020_Gaz_zcta_national.zip"
OUTPUT_DIR = Path("tools/data")
OUTPUT_PATH = OUTPUT_DIR / "zcta_centroids.tsv"
ZIP_PATH = OUTPUT_DIR / "zcta.zip"

CHUNK_SIZE = 64 * 1024


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if OUTPUT_PATH.exists():
        log.info(f"{OUTPUT_PATH} already exists ({OUTPUT_PATH.stat().st_size / 1024:.0f} KB). Delete to re-download.")
        return

    log.info(f"Downloading Census ZCTA centroid file from {CENSUS_URL}")
    resp = requests.get(CENSUS_URL, stream=True, timeout=60)
    resp.raise_for_status()

    with open(ZIP_PATH, "wb") as f:
        for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
            if chunk:
                f.write(chunk)
    log.info(f"Downloaded {ZIP_PATH.stat().st_size / 1024:.0f} KB")

    import zipfile
    with zipfile.ZipFile(ZIP_PATH) as z:
        names = z.namelist()
        log.info(f"ZIP contents: {names}")
        # The file inside is named like 2020_Gaz_zcta_national.txt
        txt_name = next((n for n in names if n.endswith(".txt")), None)
        if not txt_name:
            log.error("No .txt file found in ZIP")
            sys.exit(1)
        with z.open(txt_name) as src, open(OUTPUT_PATH, "wb") as dst:
            dst.write(src.read())

    ZIP_PATH.unlink()
    log.info(f"Extracted to {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size / 1024:.0f} KB)")
    log.info("Done. geocode.py will load this file automatically on first use.")


if __name__ == "__main__":
    main()

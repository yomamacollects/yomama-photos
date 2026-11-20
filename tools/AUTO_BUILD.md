# Hourly auto build (what Claude does on each check)

1. `git fetch origin main` in a clone of yomama-photos; list `inbox/*.json`
   (not `inbox/done/`). None: stop quietly, no message.
2. For each batch, oldest first, read the manifest:
   * `items[].sku` and `items[].photos` are final. The photos are already
     uploaded under `<date_folder>/<SKU>_1.jpg` / `_2.jpg`. Don't renumber
     or re-upload.
   * `mode: fronts_only` means PicURL = front|banner.
   * `notes` are Christian's own notes for the batch (condition overrides,
     prices). Apply them for this batch only.
   * `flags` such as "blank side" or "straightened" go in the check list.
3. Follow the project instructions and the `ebay-scheduled-listings` skill
   exactly as for a hand-sent batch (inspection checklists, pricing, groups
   of 10, file names, summary), except the photo push step. Before
   identifying each card, run
   `python tools/listing/zoom_crops.py <tmp> --manifest inbox/<batch>.json`
   and read the enlarged crops, not only the full scan.
4. Run `python tools/listing/check_listing_csv.py <group CSVs> <ALL CSV> --check-urls`.
   It must exit 0. Fix every FAIL; justify every BLANK line in the check list.
5. Save the CSVs and summary under `/mnt/project-files/listings/`, post them
   in the "Automate scanner-to-listing pipeline" thread with the go-live time
   in Eastern time.
6. `git mv inbox/<batch>.json inbox/done/` and push to main, so the batch is
   never built twice. If a batch can't be finished in one run, leave the
   manifest in `inbox/` and say what's left.

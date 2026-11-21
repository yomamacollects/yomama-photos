# YoMama scan-to-listing tools

```
scanner (PaperStream profile "YoMama Cards")
   -> E:\Scans\Claude Scans
   -> Scan Agent on the PC (pair, straighten/trim, SKUs, upload, move to "do not scan")
   -> yomama-photos: <YYYY-MM-DD>/<SKU>_1.jpg, _2.jpg  +  inbox/<batch>.json
   -> hourly Claude check: identify, price, build CSV, run build checks
   -> CSV in the project thread -> Seller Hub > Reports > Upload (one file)
```

| Folder | Runs on | What |
|---|---|---|
| `scan-agent/` | Christian's PC | background program + `setup.cmd` |
| `listing/check_listing_csv.py` | Claude | every build check from `ebay-build-checks.md`, fails the build |
| `listing/zoom_crops.py` | Claude | enlarged crops of the collector line, artist line and corner |
| `AUTO_BUILD.md` | Claude | the steps the hourly check follows |

## 1. Scanner profile (do once on each scanner)

Open **PaperStream Capture**, make a new profile named **YoMama Cards** (copy an
existing color profile), and set these. Menu names can differ a little between
PaperStream versions; the setting is what matters.

| Setting | fi-8170 | fi-800R | Why |
|---|---|---|---|
| Image type | Color | Color | |
| Resolution | 600 dpi | 600 dpi | small print (artist, set code, 1st Ed stamp) stays readable |
| Paper source | ADF / Feeder (Duplex) | Duplex (U-turn), or Return path for thick/sleeved cards | front then back, every time |
| Paper size | Automatic Detection (auto crop + deskew) | Automatic Detection | crops and straightens in the scanner |
| Blank page skip | **OFF** | **OFF** | a skipped blank back would shift every pair after it |
| Rotation | 0 / None (not Automatic) | 0 / None | automatic rotation reads card art badly; feed cards the same way up |
| Multifeed detection | On if the cards aren't sleeved; Off if it stops on every sleeved card | same | a double feed is caught by the agent's odd-count check anyway |
| File format | JPEG, high quality / low compression | JPEG, high quality | |
| Save to | `E:\Scans\Claude Scans` | `E:\Scans\Claude Scans` | |
| File name | prefix `fi8170_` + 4-digit counter, counter never resets | prefix `fi800_` + 4-digit counter | the prefix keeps each scanner's stack separate; the counter keeps scan order |

Assign the profile to the scanner's front button so one press scans the stack.

## 2. Scan Agent (do once)

1. Download the `scan-agent` folder (the zip Claude sends) and unzip it to
   `Documents\YoMama Scan Agent`.
2. Make a GitHub key: github.com > Settings > Developer settings >
   Fine-grained tokens > Generate. Repository access: **Only select
   repositories > yomama-photos**. Permissions: **Contents: Read and write**.
   Expiration: 1 year. Copy it.
3. Double-click `setup.cmd`, paste the key when asked. It installs what it
   needs, saves the key in Windows Credential Manager, and starts the agent
   every time you sign in.

### Using it

* Scan as usual. About 90 seconds after the last page, the photos go up and
  the scans move to `do not scan\<batch>` (with a `batch.txt` listing which
  scan became which SKU).
* **Notes for a batch:** drop any `.txt` file in the scan folder before or
  while scanning, e.g. `notes.txt` with "all lightly played" or "Charizard
  $40". It travels with the batch.
* **Fronts only:** add a file named `fronts only.txt`; each scan becomes one
  item with front + banner.
* **Problems:** an odd number of scans or a blank front stops that stack and
  writes `SCAN AGENT - CHECK THIS.txt` in the scan folder. Nothing is
  uploaded or moved until it's fixed; then it carries on by itself.
* `stop-agent.cmd` / `start-agent.cmd` pause and restart it (auto-start is a scheduled task, or a Startup-folder shortcut when Windows refuses the task);
  `uninstall.cmd` removes it. Its diary is `scan_agent.log`.
* Test without uploading: `py -3 scan_agent.py --dry-run C:\temp\test`.

## 3. Listings

Claude checks `inbox/` in the photo repo every hour and builds the listings
for any new batch (see `AUTO_BUILD.md`). The CSV and summary arrive in the
project thread; upload only the `_ALL_` file.

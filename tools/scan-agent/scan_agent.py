"""YoMama Scan Agent.

Watches the scanner output folder on Christian's PC. When a stack of scans
has finished (the folder has been quiet for a while) it:

  1. groups the files by scanner (file name prefix) and sorts them in scan order
  2. pairs them front/back (or one file per item when a "fronts only" note is
     in the folder)
  3. straightens and trims any scan that still has scanner background around
     the card, and flags blank or near-blank sides
  4. gives every item the next free SKU (YMC-YYYYMMDD-NN) by reading that
     day's folder in the photo repo
  5. uploads the photos plus a batch note (inbox/<batch>.json) to the photo
     repo in ONE commit, so Claude can build the listings from it
  6. moves the original scans into "do not scan\\<batch>"

Nothing is moved until the upload has succeeded. A problem (odd number of
scans, a blank front) stops that stack and writes "SCAN AGENT - CHECK THIS.txt"
into the scan folder instead.

Usage:
  pythonw scan_agent.py                 run forever (what the startup task does)
  python  scan_agent.py --once          process whatever is waiting, then exit
  python  scan_agent.py --dry-run DIR   process the waiting scans into DIR only:
                                        no upload, nothing moved (for testing)
  python  scan_agent.py --setup         store the GitHub key and check access
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import getpass
import json
import logging
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageOps

try:  # opencv is only needed for the crop/straighten step
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
LOG_PATH = HERE / "scan_agent.log"
KEYRING_SERVICE = "yomama-scan-agent"
KEYRING_USER = "github-token"

DEFAULT_CONFIG = {
    "watch_folder": r"E:\Scans\Claude Scans",
    "done_folder_name": "do not scan",
    "repo": "yomamacollects/yomama-photos",
    "branch": "main",
    "settle_seconds": 90,
    "poll_seconds": 10,
    "jpeg_quality": 92,
    "max_long_side": 2600,
    "auto_crop": True,
    "sku_prefix": "YMC",
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
PROBLEM_FILE = "SCAN AGENT - CHECK THIS.txt"
RAW_BASE = "https://raw.githubusercontent.com/{repo}/{branch}/"
API = "https://api.github.com"

log = logging.getLogger("scan_agent")


# --------------------------------------------------------------------------
# config and secrets
# --------------------------------------------------------------------------

def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    return cfg


def get_token() -> str:
    tok = os.environ.get("YOMAMA_GH_TOKEN")
    if tok:
        return tok.strip()
    try:
        import keyring

        tok = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:  # keyring missing or locked
        tok = None
    if not tok:
        raise SystemExit("No GitHub key stored. Run setup.cmd (or scan_agent.py --setup) first.")
    return tok.strip()


# --------------------------------------------------------------------------
# GitHub (REST API only, so no git install or local clone is needed)
# --------------------------------------------------------------------------

class GitHub:
    def __init__(self, repo: str, branch: str, token: str):
        self.repo, self.branch = repo, branch
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "yomama-scan-agent",
        })

    def _req(self, method: str, path: str, ok=(200, 201), **kw):
        url = f"{API}/repos/{self.repo}/{path}"
        for attempt in range(5):
            try:
                r = self.s.request(method, url, timeout=120, **kw)
            except requests.RequestException as e:
                log.warning("network error %s, retrying: %s", path, e)
                time.sleep(2 ** attempt)
                continue
            if r.status_code in ok:
                return r
            if r.status_code in (500, 502, 503, 504) or (r.status_code == 403 and "rate" in r.text.lower()):
                time.sleep(2 ** attempt + 1)
                continue
            return r
        raise RuntimeError(f"GitHub {method} {path} kept failing")

    def check_access(self) -> str:
        r = self._req("GET", "")
        if r.status_code != 200:
            return f"cannot read {self.repo}: HTTP {r.status_code} {r.text[:200]}"
        perms = r.json().get("permissions") or {}
        if perms and not perms.get("push"):
            return f"the key can read {self.repo} but cannot upload to it (needs Contents: Read and write)"
        return ""

    def list_dir(self, path: str) -> list[str]:
        r = self._req("GET", f"contents/{path}?ref={self.branch}", ok=(200, 404))
        if r.status_code == 404:
            return []
        if r.status_code != 200:
            raise RuntimeError(f"list {path}: HTTP {r.status_code} {r.text[:200]}")
        data = r.json()
        return [d["name"] for d in data] if isinstance(data, list) else []

    def head(self) -> tuple[str, str]:
        r = self._req("GET", f"git/ref/heads/{self.branch}")
        if r.status_code != 200:
            raise RuntimeError(f"read branch: HTTP {r.status_code} {r.text[:200]}")
        commit_sha = r.json()["object"]["sha"]
        c = self._req("GET", f"git/commits/{commit_sha}").json()
        return commit_sha, c["tree"]["sha"]

    def blob(self, data: bytes) -> str:
        r = self._req("POST", "git/blobs", json={"content": base64.b64encode(data).decode(), "encoding": "base64"})
        if r.status_code != 201:
            raise RuntimeError(f"upload blob: HTTP {r.status_code} {r.text[:200]}")
        return r.json()["sha"]

    def commit_files(self, files: dict[str, str], message: str) -> str | None:
        """files: repo path -> blob sha. Returns the commit sha, or None when
        the branch moved underneath us (caller re-reads and retries)."""
        parent, base_tree = self.head()
        tree = [{"path": p, "mode": "100644", "type": "blob", "sha": sha} for p, sha in files.items()]
        t = self._req("POST", "git/trees", json={"base_tree": base_tree, "tree": tree})
        if t.status_code != 201:
            raise RuntimeError(f"tree: HTTP {t.status_code} {t.text[:200]}")
        c = self._req("POST", "git/commits", json={"message": message, "tree": t.json()["sha"], "parents": [parent]})
        if c.status_code != 201:
            raise RuntimeError(f"commit: HTTP {c.status_code} {c.text[:200]}")
        sha = c.json()["sha"]
        u = self._req("PATCH", f"git/refs/heads/{self.branch}", ok=(200, 422), json={"sha": sha, "force": False})
        if u.status_code == 422:  # someone else pushed first
            return None
        return sha


# --------------------------------------------------------------------------
# finding and grouping scans
# --------------------------------------------------------------------------

def natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def group_prefix(stem: str) -> str:
    """'fi800_0007' -> 'fi800_'; '20261120_0012' -> '20261120_'. Files from the
    two scanners get different prefixes, so a stack from each never mixes."""
    return re.sub(r"\d+$", "", stem)


@dataclass
class Stack:
    prefix: str
    images: list[Path]
    fronts_only: bool = False
    notes: str = ""
    control_files: list[Path] = field(default_factory=list)


def scan_folder(folder: Path) -> tuple[list[Path], list[Path]]:
    images, texts = [], []
    for p in folder.iterdir():
        if not p.is_file() or p.suffix.lower() == ".lnk" or p.name.startswith(("~", ".")):
            continue
        if p.suffix.lower() in IMAGE_EXTS:
            images.append(p)
        elif p.suffix.lower() == ".txt" and p.name != PROBLEM_FILE:
            texts.append(p)
    return images, texts


def build_stacks(images: list[Path], texts: list[Path]) -> list[Stack]:
    fronts_only = any("front" in t.stem.lower() and "only" in t.stem.lower() for t in texts)
    notes = []
    for t in texts:
        try:
            body = t.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            body = ""
        notes.append(f"[{t.name}] {body}".strip())
    groups: dict[str, list[Path]] = {}
    for p in images:
        groups.setdefault(group_prefix(p.stem), []).append(p)
    stacks = []
    for prefix, files in sorted(groups.items()):
        files.sort(key=lambda p: (natural_key(p.name), p.stat().st_mtime))
        stacks.append(Stack(prefix, files, fronts_only, "\n".join(notes), list(texts)))
    return stacks


class Settle:
    """Folder counts as finished when no image appeared, grew or changed for
    settle_seconds."""

    def __init__(self, seconds: int):
        self.seconds = seconds
        self.last_sig = None
        self.failed_sig = None
        self.since = time.time()

    def ready(self, images: list[Path]) -> bool:
        sig = tuple(sorted((p.name, p.stat().st_size, int(p.stat().st_mtime)) for p in images))
        now = time.time()
        if sig != self.last_sig:
            self.last_sig, self.since = sig, now
        newest = max((p.stat().st_mtime for p in images), default=0)
        return bool(images) and now - self.since >= self.seconds and now - newest >= self.seconds


# --------------------------------------------------------------------------
# image clean-up
# --------------------------------------------------------------------------

def is_blank(img: Image.Image) -> bool:
    g = np.asarray(img.convert("L").resize((200, 280)), dtype=np.float32)
    return float(g.std()) < 7.0


def crop_and_straighten(img: Image.Image) -> tuple[Image.Image, str]:
    """Only acts when the scan clearly still has scanner background around the
    card (PaperStream's own auto-crop normally already did the job). Returns
    the image and a short note of what changed."""
    if cv2 is None:
        return img, ""
    a = np.asarray(img.convert("RGB"))
    h, w = a.shape[:2]
    b = max(4, min(h, w) // 100)
    border = np.concatenate([a[:b].reshape(-1, 3), a[-b:].reshape(-1, 3), a[:, :b].reshape(-1, 3), a[:, -b:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    if np.abs(border.astype(int) - bg).max(axis=1).mean() > 40:
        return img, ""  # border is not one plain colour: already cropped to the card
    diff = np.abs(a.astype(np.int16) - bg.astype(np.int16)).max(axis=2)
    mask = (diff > 35).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return img, ""
    c = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.15 * h * w:
        return img, ""
    (cx, cy), (rw, rh), ang = cv2.minAreaRect(c)
    if ang > 45:
        ang -= 90
    if rw * rh > 0.85 * h * w and abs(ang) < 0.3:
        return img, ""  # card already fills the scan: leave it exactly as scanned
    notes = []
    out = img
    if 0.3 <= abs(ang) <= 15:
        out = img.rotate(ang, resample=Image.BICUBIC, expand=True, fillcolor=tuple(int(v) for v in bg))
        notes.append(f"straightened {ang:+.1f} deg")
        a = np.asarray(out.convert("RGB"))
        h, w = a.shape[:2]
        diff = np.abs(a.astype(np.int16) - bg.astype(np.int16)).max(axis=2)
        mask = cv2.morphologyEx((diff > 35).astype(np.uint8) * 255, cv2.MORPH_CLOSE, k, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        c = max(cnts, key=cv2.contourArea)
    x, y, cw, ch = cv2.boundingRect(c)
    pad = int(0.012 * max(cw, ch))
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(w, x + cw + pad), min(h, y + ch + pad)
    if (x1 - x0) * (y1 - y0) < 0.85 * w * h:  # only trim a clearly loose crop
        out = out.crop((x0, y0, x1, y1))
        notes.append("trimmed background")
    return out, ", ".join(notes)


def prepare(path: Path, cfg: dict) -> tuple[bytes, list[str]]:
    flags: list[str] = []
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        dpi = im.info.get("dpi", (600, 600))
        im = im.convert("RGB")
    if is_blank(im):
        flags.append("blank side")
    elif cfg.get("auto_crop", True):
        im, note = crop_and_straighten(im)
        if note:
            flags.append(note)
    m = int(cfg.get("max_long_side") or 0)
    if m and max(im.size) > m:
        s = m / max(im.size)
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    buf = BytesIO()
    im.save(buf, "JPEG", quality=int(cfg["jpeg_quality"]), optimize=True, dpi=dpi, subsampling=0)
    return buf.getvalue(), flags


# --------------------------------------------------------------------------
# the batch itself
# --------------------------------------------------------------------------

class StackProblem(Exception):
    pass


def make_items(stack: Stack) -> list[list[Path]]:
    if stack.fronts_only:
        return [[p] for p in stack.images]
    if len(stack.images) % 2:
        names = ", ".join(p.name for p in stack.images[-3:])
        raise StackProblem(
            f"{len(stack.images)} scans with prefix '{stack.prefix}' is an odd number, so fronts and backs "
            f"can't be paired. A card may have double-fed or a side is missing (last files: {names}). "
            "Rescan the missing side, or if every back is blank add a text file named 'fronts only.txt'.")
    return [stack.images[i:i + 2] for i in range(0, len(stack.images), 2)]


def next_sku_number(existing: list[str], day: str, prefix: str) -> int:
    pat = re.compile(rf"^{re.escape(prefix)}-{day}-(\d+)_")
    nums = [int(m.group(1)) for n in existing if (m := pat.match(n))]
    return max(nums, default=0) + 1


def process_stack(stack: Stack, cfg: dict, gh: GitHub | None, dry_dir: Path | None) -> dict:
    items = make_items(stack)
    prepared = []
    for files in items:
        sides = [prepare(p, cfg) for p in files]
        flags = []
        for side, (_, f) in zip(("front", "back"), sides):
            flags += [f"{side}: {x}" for x in f]
        if not stack.fronts_only and "front: blank side" in flags:
            raise StackProblem(
                f"The front scan {files[0].name} looks blank. A card may have double-fed, which would shift "
                "every pair after it. Check the stack and rescan from that card.")
        prepared.append((files, [d for d, _ in sides], flags))

    now = dt.datetime.now()
    day, day_dash = now.strftime("%Y%m%d"), now.strftime("%Y-%m-%d")
    batch_id = now.strftime("%Y%m%d-%H%M%S") + (f"-{stack.prefix.strip('_- ')}" if stack.prefix.strip("_- ") else "")
    raw = RAW_BASE.format(repo=cfg["repo"], branch=cfg["branch"])

    blobs: list[list[str]] = []
    if gh:
        for _, datas, _ in prepared:
            blobs.append([gh.blob(d) for d in datas])

    for attempt in range(6):
        existing = gh.list_dir(day_dash) if gh else (sorted(os.listdir(dry_dir / day_dash)) if dry_dir and (dry_dir / day_dash).exists() else [])
        n0 = next_sku_number(existing, day, cfg["sku_prefix"])
        manifest_items, files_map = [], {}
        for i, (files, datas, flags) in enumerate(prepared):
            sku = f"{cfg['sku_prefix']}-{day}-{n0 + i:02d}"
            paths = [f"{day_dash}/{sku}_{k + 1}.jpg" for k in range(len(datas))]
            for k, path in enumerate(paths):
                files_map[path] = blobs[i][k] if gh else datas[k]
            manifest_items.append({
                "sku": sku,
                "photos": [raw + p for p in paths],
                "source_files": [p.name for p in files],
                "flags": flags,
            })
        manifest = {
            "batch_id": batch_id,
            "created_local": now.isoformat(timespec="seconds"),
            "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "date_folder": day_dash,
            "mode": "fronts_only" if stack.fronts_only else "pairs",
            "scanner_prefix": stack.prefix,
            "notes": stack.notes,
            "count": len(manifest_items),
            "first_sku": manifest_items[0]["sku"],
            "last_sku": manifest_items[-1]["sku"],
            "items": manifest_items,
        }
        mbytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        mpath = f"inbox/{batch_id}.json"
        if not gh:
            for path, data in list(files_map.items()) + [(mpath, mbytes)]:
                out = dry_dir / path
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
            return manifest
        files_map[mpath] = gh.blob(mbytes)
        msg = f"Scan Agent: {manifest['count']} items {manifest['first_sku']}..{manifest['last_sku']} (batch {batch_id})"
        if gh.commit_files(files_map, msg):
            return manifest
        log.info("branch moved while uploading, renumbering and retrying (%d)", attempt + 1)
        time.sleep(3)
    raise RuntimeError("could not upload: the photo repo kept changing underneath the upload")


def move_done(stack: Stack, folder: Path, cfg: dict, manifest: dict) -> None:
    dest = folder / cfg["done_folder_name"] / manifest["batch_id"]
    dest.mkdir(parents=True, exist_ok=True)
    for p in stack.images:
        shutil.move(str(p), str(dest / p.name))
    for t in stack.control_files:
        if t.exists():
            shutil.move(str(t), str(dest / t.name))
    lines = [f"Batch {manifest['batch_id']}: {manifest['count']} items, {manifest['first_sku']} .. {manifest['last_sku']}", ""]
    for it in manifest["items"]:
        lines.append(f"{it['sku']}: {' + '.join(it['source_files'])}" + (f"   ({'; '.join(it['flags'])})" if it["flags"] else ""))
    (dest / "batch.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_problem(folder: Path, text: str) -> None:
    (folder / PROBLEM_FILE).write_text(
        f"{dt.datetime.now():%Y-%m-%d %H:%M}\n\n{text}\n\nNothing was uploaded or moved for this stack. "
        "Fix it and the Scan Agent will try again by itself; you can delete this file.\n", encoding="utf-8")


def clear_problem(folder: Path) -> None:
    try:
        (folder / PROBLEM_FILE).unlink()
    except FileNotFoundError:
        pass


def run_once(cfg: dict, gh: GitHub | None, dry_dir: Path | None, settle: Settle | None) -> int:
    folder = Path(cfg["watch_folder"])
    images, texts = scan_folder(folder)
    if not images or (settle and not settle.ready(images)):
        return 0
    if settle and settle.failed_sig == settle.last_sig:
        return 0  # same files that already failed; wait until something changes
    done = 0
    problems = []
    for stack in build_stacks(images, texts):
        try:
            manifest = process_stack(stack, cfg, gh, dry_dir)
        except StackProblem as e:
            log.warning("stack %s: %s", stack.prefix, e)
            problems.append(str(e))
            continue
        log.info("uploaded %d items %s..%s", manifest["count"], manifest["first_sku"], manifest["last_sku"])
        if gh:
            move_done(stack, folder, cfg, manifest)
        done += manifest["count"]
    if problems:
        write_problem(folder, "\n\n".join(problems))
        if settle:
            settle.failed_sig = settle.last_sig
    else:
        clear_problem(folder)
    return done


def setup() -> None:
    cfg = load_config()
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
    print(f"Photo repo: {cfg['repo']}   Scan folder: {cfg['watch_folder']}")
    tok = getpass.getpass("Paste your GitHub access key (it stays hidden) and press Enter: ").strip()
    gh = GitHub(cfg["repo"], cfg["branch"], tok)
    err = gh.check_access()
    if err:
        raise SystemExit("That key didn't work: " + err)
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, tok)
    print("Key works and is saved in Windows Credential Manager.")
    if not Path(cfg["watch_folder"]).is_dir():
        print(f"WARNING: the scan folder {cfg['watch_folder']} doesn't exist yet. Edit config.json if it moved.")


_LOCK = None


def single_instance() -> None:
    """Exit if another copy is already running (two copies would upload the
    same stack twice)."""
    global _LOCK
    _LOCK = open(HERE / "agent.lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(_LOCK.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(_LOCK.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit("The Scan Agent is already running (stop it with stop-agent.cmd first).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", metavar="DIR")
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--folder", help="scan folder (overrides config.json)")
    args = ap.parse_args()

    handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stdout and sys.stdout.isatty():
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)

    if args.setup:
        setup()
        return
    cfg = load_config()
    if args.folder:
        cfg["watch_folder"] = args.folder
    if args.dry_run:
        n = run_once(cfg, None, Path(args.dry_run), None)
        print(f"dry run: {n} items written to {args.dry_run}")
        return
    single_instance()
    gh = GitHub(cfg["repo"], cfg["branch"], get_token())
    err = gh.check_access()
    if err:
        log.error(err)
        raise SystemExit(err)
    if args.once:
        print(f"{run_once(cfg, gh, None, None)} items uploaded")
        return
    log.info("watching %s", cfg["watch_folder"])
    settle = Settle(int(cfg["settle_seconds"]))
    while True:
        try:
            run_once(cfg, gh, None, settle)
        except Exception:
            log.exception("error, will retry")
        time.sleep(int(cfg["poll_seconds"]))


if __name__ == "__main__":
    main()

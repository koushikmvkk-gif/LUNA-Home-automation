"""USB pen drives and file helpers: detect drives, browse folders, copy files, backup, eject, find documents."""
import glob
import logging
import os
import shutil
import subprocess

from .music import AUDIO_EXTS, norm, score
from .media import VIDEO_EXTS

log = logging.getLogger("files")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")


def kind_of(path):
    p = path.lower()
    if os.path.isdir(path):
        return "folder"
    if p.endswith(".pdf"):
        return "pdf"
    if p.endswith((".txt", ".md")):
        return "text"
    if p.endswith(IMAGE_EXTS):
        return "image"
    if p.endswith(AUDIO_EXTS):
        return "audio"
    if p.endswith(VIDEO_EXTS):
        return "video"
    return "other"


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "%d %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0


def usb_drives(cfg):
    """-> list of dict(label, path, free, total) for every mounted pen drive."""
    from . import usbmon
    try:
        return list(usbmon.scan(cfg).values())
    except Exception as e:
        log.info("usb scan failed: %s", e)
        return []


def _usb_drives_old(cfg):
    out, seen = [], set()
    for pat in cfg.USB_ROOTS:
        for p in sorted(glob.glob(pat)):
            if not os.path.isdir(p) or p in seen:
                continue
            if cfg.USB_REQUIRE_MOUNT and not os.path.ismount(p):
                continue
            seen.add(p)
            try:
                du = shutil.disk_usage(p)
                free, total = du.free, du.total
            except OSError:
                free = total = 0
            out.append(dict(label=os.path.basename(p), path=p, free=free, total=total))
    return out


def list_dir(path):
    """Folders first, then files; hidden entries skipped. -> list of (name, full_path, kind, size)."""
    items = []
    try:
        names = os.listdir(path)
    except OSError:
        return items
    for n in names:
        if n.startswith(".") or n.lower() in ("system volume information", "$recycle.bin"):
            continue
        fp = os.path.join(path, n)
        k = kind_of(fp)
        try:
            size = os.path.getsize(fp) if k != "folder" else len(os.listdir(fp))
        except OSError:
            size = 0
        items.append((n, fp, k, size))
    return sorted(items, key=lambda x: (x[2] != "folder", x[0].lower()))


def copy_into(src, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(src))
    if os.path.exists(dest):
        base, ext = os.path.splitext(os.path.basename(src))
        dest = os.path.join(dest_dir, "%s_copy%s" % (base, ext))
    shutil.copy2(src, dest)
    return dest


def copy_to_luna(cfg, src):
    """Copy a file from a USB drive into the right Luna folder. Returns a message."""
    k = kind_of(src)
    dest = {"pdf": cfg.PDF_DIR, "audio": os.path.join(cfg.MUSIC_DIR, "Imported"), "video": cfg.MOVIES_DIR, "image": cfg.GALLERY_DIR, "text": cfg.PDF_DIR}.get(k)
    if not dest:
        return "Luna cannot store this file type"
    copy_into(src, dest)
    return "Copied to Luna (%s)" % {"pdf": "Documents", "audio": "Music / Imported", "video": "Movies", "image": "Gallery", "text": "Documents"}[k]


def backup_to_usb(cfg, drive_path):
    """Copy gallery photos/videos and drawings (NOT the hidden gallery) to <drive>/Luna_Backup/. -> number of files."""
    n = 0
    for src_dir, name in ((cfg.GALLERY_DIR, "Gallery"), (cfg.DRAWINGS_DIR, "Drawings")):
        if not os.path.isdir(src_dir):
            continue
        dest = os.path.join(drive_path, "Luna_Backup", name)
        os.makedirs(dest, exist_ok=True)
        for f in os.listdir(src_dir):
            s, d = os.path.join(src_dir, f), os.path.join(dest, f)
            if os.path.isfile(s) and not os.path.exists(d):
                shutil.copy2(s, d)
                n += 1
    try:
        os.sync()
    except Exception:
        pass
    return n


def eject(path):
    """Flush + unmount + power off. Returns (ok, message)."""
    from . import usbmon
    return usbmon.safe_eject(path)


def find_pdf(cfg, query):
    """Fuzzy-find a PDF by (part of) its name in data/pdfs and on USB drives."""
    best, best_s = None, 0.0
    roots = [cfg.PDF_DIR] + [d["path"] for d in usb_drives(cfg)]
    count = 0
    for root in roots:
        base_depth = root.rstrip("/").count("/")
        for dp, dns, fns in os.walk(root):
            if dp.count("/") - base_depth >= 4:
                dns[:] = []
            dns[:] = [d for d in dns if not d.startswith(".")]
            for f in fns:
                if f.lower().endswith(".pdf"):
                    count += 1
                    s = score(query, os.path.splitext(f)[0])
                    if s > best_s:
                        best, best_s = os.path.join(dp, f), s
            if count > 4000:
                break
    return best if best_s >= 0.55 else None


def list_pdfs(cfg):
    d = cfg.PDF_DIR
    os.makedirs(d, exist_ok=True)
    return sorted([os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".pdf")], key=lambda p: os.path.basename(p).lower())

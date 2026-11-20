"""USB pen-drive monitor + safe eject.

A small polling daemon (pyudev is used as a wake-up trigger when it is installed, but is NOT required) watches
/media/$USER/, /media/, /run/media/$USER/ and the patterns in config.USB_ROOTS. It posts ("usb", ("in", drive))
and ("usb", ("out", path)) events into the app's event queue, so the UI thread does all the drawing.
"""
import getpass
import glob
import logging
import os
import shutil
import subprocess
import threading
import time

log = logging.getLogger("usbmon")


def roots(cfg):
    user = getpass.getuser()
    pats = ["/media/%s/*" % user, "/run/media/%s/*" % user, "/media/*"] + list(cfg.USB_ROOTS)
    seen, out = set(), []
    for p in pats:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def scan(cfg):
    """-> {path: dict(label, path, free, total)} for every mounted removable volume."""
    found = {}
    for pat in roots(cfg):
        for p in sorted(glob.glob(pat)):
            if p in found or not os.path.isdir(p):
                continue
            if cfg.USB_REQUIRE_MOUNT and not os.path.ismount(p):
                continue
            if p.rstrip("/") in ("/media", "/run/media", "/mnt", "/media/" + getpass.getuser()):
                continue
            try:
                du = shutil.disk_usage(p)
                free, total = du.free, du.total
            except OSError:
                continue
            found[p] = dict(label=os.path.basename(p), path=p, free=free, total=total)
    return found


class USBMonitor(threading.Thread):
    def __init__(self, cfg, events, simulate=False):
        super().__init__(daemon=True, name="usbmon")
        self.cfg, self.events, self.sim = cfg, events, simulate
        self.drives = {}
        self.present = False
        self.running = True
        self._wake = threading.Event()

    def run(self):
        self.drives = scan(self.cfg)
        self.present = bool(self.drives)
        self._try_udev()
        while self.running:
            self._wake.wait(self.cfg.USB_POLL_S)
            self._wake.clear()
            try:
                cur = scan(self.cfg)
            except Exception:
                log.exception("scan failed")
                continue
            for p, d in cur.items():
                if p not in self.drives:
                    log.info("USB in: %s", p)
                    self.events.put(("usb", ("in", d)))
            for p in self.drives:
                if p not in cur:
                    log.info("USB out: %s", p)
                    self.events.put(("usb", ("out", p)))
            self.drives = cur
            self.present = bool(cur)

    def _try_udev(self):
        """Optional: wake the poller instantly on a block-device event (pip install pyudev)."""
        try:
            import pyudev
            ctx = pyudev.Context()
            mon = pyudev.Monitor.from_netlink(ctx)
            mon.filter_by("block")
            obs = pyudev.MonitorObserver(mon, callback=lambda dev: (time.sleep(1.5), self._wake.set()))
            obs.daemon = True
            obs.start()
            log.info("pyudev trigger enabled")
        except Exception:
            pass

    def stop(self):
        self.running = False
        self._wake.set()


def safe_eject(path):
    """Flush buffers (sync), unmount cleanly, power the stick off. -> (ok, message)."""
    try:
        os.sync()
        subprocess.run(["sync", "-f", path], capture_output=True, timeout=60)
    except Exception as e:
        log.info("sync: %s", e)
    try:
        src = subprocess.run(["findmnt", "-n", "-o", "SOURCE", path], capture_output=True, text=True, timeout=5).stdout.strip()
        ok = False
        if src:
            r = subprocess.run(["udisksctl", "unmount", "-b", src], capture_output=True, text=True, timeout=30)
            ok = r.returncode == 0
            if ok:
                subprocess.run(["udisksctl", "power-off", "-b", src.rstrip("0123456789")], capture_output=True, timeout=15)
            elif "busy" in (r.stderr or "").lower():
                return False, "Drive is busy - close the file that is open on it"
        if not ok:
            ok = subprocess.run(["umount", path], capture_output=True, timeout=30).returncode == 0
        return (True, "You can remove the USB drive now") if ok else (False, "Could not eject - is a file still open?")
    except Exception as e:
        log.info("eject failed: %s", e)
        return False, "Eject failed"

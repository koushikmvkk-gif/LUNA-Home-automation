"""Wi-Fi (NetworkManager / nmcli) and Bluetooth (bluetoothctl) managers. Both have a simulator for --sim."""
import logging
import re
import shutil
import subprocess
import time

log = logging.getLogger("net")


def run(cmd, timeout=15):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, str(e)


def split_nm(line):
    return [x.replace("\\:", ":") for x in re.split(r"(?<!\\):", line)]


class WifiManager:
    def __init__(self, simulate=False):
        self.sim = simulate
        self.available = simulate or shutil.which("nmcli") is not None
        self._sim_active = "HomeWiFi"
        self._sim_saved = {"HomeWiFi"}

    def scan(self):
        """-> list of dict(ssid, signal, secure, active, saved), strongest first."""
        if self.sim:
            nets = [("HomeWiFi", 82, True), ("Neighbour_5G", 55, True), ("CafeFree", 40, False), ("Office-Net", 30, True)]
            return [dict(ssid=s, signal=g, secure=sec, active=(s == self._sim_active), saved=s in self._sim_saved) for s, g, sec in nets]
        if not self.available:
            return []
        rc, out = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes"], 25)
        saved = self.saved()
        best = {}
        for line in out.splitlines():
            p = split_nm(line)
            if len(p) < 4 or not p[1]:
                continue
            d = dict(ssid=p[1], signal=int(p[2] or 0), secure=bool(p[3].strip()), active=p[0].strip() == "*", saved=p[1] in saved)
            if p[1] not in best or d["signal"] > best[p[1]]["signal"] or d["active"]:
                best[p[1]] = d
        return sorted(best.values(), key=lambda d: (not d["active"], -d["signal"]))

    def active(self):
        if self.sim:
            return self._sim_active
        rc, out = run(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"])
        for l in out.splitlines():
            p = split_nm(l)
            if len(p) > 1 and p[0] == "yes":
                return p[1]
        return None

    def saved(self):
        if self.sim:
            return set(self._sim_saved)
        rc, out = run(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show"])
        return {split_nm(l)[0] for l in out.splitlines() if "wireless" in l}

    def connect(self, ssid, password=None):
        if self.sim:
            time.sleep(1.0)
            if password is not None and password == "wrong":
                return False, "Wrong password"
            self._sim_active = ssid
            self._sim_saved.add(ssid)
            return True, "Connected to %s" % ssid
        cmd = ["nmcli", "dev", "wifi", "connect", ssid]
        if password:
            cmd += ["password", password]
        rc, out = run(cmd, 40)
        if rc == 0:
            return True, "Connected to %s" % ssid
        low = out.lower()
        return False, "Wrong password" if ("secrets" in low or "password" in low) else (out.strip().splitlines()[-1][:80] if out.strip() else "Could not connect")

    def disconnect(self):
        if self.sim:
            self._sim_active = None
            return True
        rc, out = run(["nmcli", "-t", "-f", "DEVICE,TYPE", "dev"])
        for l in out.splitlines():
            d = split_nm(l)
            if len(d) > 1 and d[1] == "wifi":
                return run(["nmcli", "dev", "disconnect", d[0]])[0] == 0
        return False

    def forget(self, ssid):
        if self.sim:
            self._sim_saved.discard(ssid)
            return True
        return run(["nmcli", "con", "delete", "id", ssid])[0] == 0


class BluetoothManager:
    def __init__(self, simulate=False):
        self.sim = simulate
        self.available = simulate or shutil.which("bluetoothctl") is not None
        self._sim = {"AA:BB:CC:00:00:01": dict(name="JBL Flip Speaker", paired=True, connected=True),
                     "AA:BB:CC:00:00:02": dict(name="Boat Earbuds", paired=True, connected=False)}
        self._sim_new = {"AA:BB:CC:00:00:03": dict(name="Mi Speaker", paired=False, connected=False)}

    def devices(self, scan=False):
        """-> list of dict(mac, name, paired, connected)."""
        if self.sim:
            if scan:
                time.sleep(0.8)
                self._sim.update(self._sim_new)
            return [dict(mac=m, **d) for m, d in self._sim.items()]
        if not self.available:
            return []
        run(["bluetoothctl", "power", "on"])
        if scan:
            run(["bluetoothctl", "--timeout", "8", "scan", "on"], 20)
        rc, out = run(["bluetoothctl", "devices"])
        devs = []
        for l in out.splitlines()[:25]:
            m = re.match(r"Device ([0-9A-F:]{17}) (.*)", l.strip(), re.I)
            if not m:
                continue
            info = run(["bluetoothctl", "info", m.group(1)])[1]
            devs.append(dict(mac=m.group(1), name=m.group(2), paired="Paired: yes" in info, connected="Connected: yes" in info))
        return sorted(devs, key=lambda d: (not d["connected"], not d["paired"], d["name"].lower()))

    def connect(self, mac):
        if self.sim:
            time.sleep(0.8)
            for m, d in self._sim.items():
                if "Speaker" in d["name"] and d["connected"] and m != mac:
                    d["connected"] = False
            self._sim[mac]["paired"] = self._sim[mac]["connected"] = True
            return True, "Connected"
        run(["bluetoothctl", "pair", mac], 25)
        run(["bluetoothctl", "trust", mac])
        rc, out = run(["bluetoothctl", "connect", mac], 25)
        return ("Connection successful" in out or rc == 0 and "Failed" not in out), ("Connected" if "successful" in out else out.strip().splitlines()[-1][:80] if out.strip() else "Failed")

    def disconnect(self, mac):
        if self.sim:
            self._sim[mac]["connected"] = False
            return True
        return run(["bluetoothctl", "disconnect", mac])[0] == 0

    def remove(self, mac):
        if self.sim:
            self._sim.pop(mac, None)
            return True
        return run(["bluetoothctl", "remove", mac])[0] == 0

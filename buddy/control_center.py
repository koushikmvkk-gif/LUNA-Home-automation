"""Hardware Control Center: ESP32 + MG90 servo switch nodes over the local Wi-Fi (REST).

Pieces
------
Esp32Api        tiny HTTP client for the firmware  (GET /api/info, GET /api/status, POST /api/servo, POST /api/calibrate)
ControlCenter   registry (data/esp32.json), background health poll + mDNS discovery, async switch dispatch, voice lookup
ControlCenterScreen   the "Control Center" tile: Nodes tab (list / add / servo count) + Switchboard tab (toggles)

Everything that touches the network runs in a worker thread; results come back to the UI thread through
app.events (("call", (fn, arg))). A failed switch never raises into the main loop.
"""
import json
import logging
import os
import re
import socket
import subprocess
import threading
import time

import pygame

from .face import font
from .screens import AMBER, BG, BLUE, CARD, GREEN, MUTED, PURPLE, RED, TEXT, TRACK, button, inside
from .ui import ListView, Screen, icon
from .util import guarded, mix

log = logging.getLogger("control")


# =============================================================================== HTTP client for the firmware
class Esp32Api:
    def __init__(self, cfg, simulate=False):
        self.cfg, self.sim = cfg, simulate
        self._sim_state = {}

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.cfg.ESP32_API_KEY:
            h["X-Luna-Key"] = self.cfg.ESP32_API_KEY
        return h

    @staticmethod
    def resolve(host):
        """Hostname / mDNS name / IP -> IPv4 string (or None)."""
        if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host):
            return host
        try:
            return socket.getaddrinfo(host, 80, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        except OSError:
            pass
        if host.endswith(".local"):                                  # avahi fallback
            try:
                out = subprocess.run(["avahi-resolve", "-4", "-n", host], capture_output=True, text=True, timeout=4).stdout.split()
                if len(out) >= 2:
                    return out[1]
            except Exception:
                pass
        return None

    def base(self, node):
        ip = self.resolve(node.get("host", "")) or node.get("ip")
        return ("http://%s:%d" % (ip, int(node.get("port", 80))), ip) if ip else (None, None)

    def info(self, node):
        """-> dict or None."""
        if self.sim:
            return dict(name="sim-esp32", servos=4, ip="192.168.1.50")
        import requests
        base, ip = self.base(node)
        if not base:
            return None
        try:
            r = requests.get(base + "/api/info", headers=self._headers(), timeout=self.cfg.ESP32_TIMEOUT_S)
            if r.status_code == 200:
                d = r.json()
                d["ip"] = ip
                return d
        except Exception as e:
            log.debug("info %s: %s", node.get("host"), e)
        return None

    def status(self, node):
        if self.sim:
            return dict(ok=True, ip="192.168.1.50", rssi=-52, servos=[dict(id=i, state=self._sim_state.get((node["id"], i), "off")) for i in range(4)])
        import requests
        base, ip = self.base(node)
        if not base:
            return None
        try:
            r = requests.get(base + "/api/status", headers=self._headers(), timeout=self.cfg.ESP32_TIMEOUT_S)
            if r.status_code == 200:
                d = r.json()
                d["ip"] = ip
                return d
        except Exception as e:
            log.debug("status %s: %s", node.get("host"), e)
        return None

    def servo(self, node, servo_id, action, angle=None):
        """POST /api/servo -> (ok, message). ok only when the ESP32 answers 200 OK with {"ok": true}."""
        if self.sim:
            self._sim_state[(node["id"], servo_id)] = action
            time.sleep(0.2)
            return True, "OK (simulated)"
        import requests
        base, ip = self.base(node)
        if not base:
            return False, "Cannot find %s on the network" % node.get("host")
        body = {"servo_id": int(servo_id), "action": action}
        if angle is not None:
            body["angle"] = int(angle)
        try:
            r = requests.post(base + "/api/servo", data=json.dumps(body), headers=self._headers(), timeout=self.cfg.ESP32_TIMEOUT_S)
        except requests.exceptions.Timeout:
            return False, "The ESP32 did not answer in time"
        except Exception as e:
            return False, "No connection to the ESP32"
        if r.status_code != 200:
            return False, "ESP32 answered %d" % r.status_code
        try:
            return (bool(r.json().get("ok", True)), "OK")
        except Exception:
            return True, "OK"

    def calibrate(self, node, servo_id, neutral):
        if self.sim:
            return True
        import requests
        base, _ = self.base(node)
        try:
            r = requests.post(base + "/api/calibrate", data=json.dumps({"servo_id": servo_id, "neutral": int(neutral)}), headers=self._headers(),
                              timeout=self.cfg.ESP32_TIMEOUT_S)
            return r.status_code == 200
        except Exception:
            return False


# =============================================================================== manager
GENERIC = {"light", "lights", "lamp", "switch", "switches", "bulb", "tube", "tubelight"}


class ControlCenter:
    def __init__(self, cfg, simulate=False):
        self.cfg, self.sim = cfg, simulate
        self.api = Esp32Api(cfg, simulate)
        self.lock = threading.RLock()
        self.nodes = []
        self.net = {}                       # node_id -> dict(online, ip, last_seen, rssi)
        self.busy = set()                   # (node_id, servo) currently moving
        self.post = lambda fn, arg: fn(arg)  # replaced by the app (runs fn(arg) on the UI thread)
        self.on_found = None                 # callback(node) when mDNS discovery adds a node
        self.running = True
        self._load()

    # ---------------------------------------------------------- storage
    def _load(self):
        try:
            with open(self.cfg.ESP32_FILE) as f:
                self.nodes = json.load(f).get("nodes", [])
        except FileNotFoundError:
            self.nodes = []
        except Exception as e:
            log.warning("cannot read esp32.json: %s", e)
            self.nodes = []
        for n in self.nodes:
            self._fix(n)

    def save(self):
        with self.lock:
            os.makedirs(os.path.dirname(self.cfg.ESP32_FILE), exist_ok=True)
            tmp = self.cfg.ESP32_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"nodes": self.nodes}, f, indent=1)
            os.replace(tmp, self.cfg.ESP32_FILE)

    @staticmethod
    def _fix(n):
        n.setdefault("port", 80)
        n["servos"] = max(1, min(4, int(n.get("servos", 1))))
        sw = {s["servo"]: s for s in n.get("switches", [])}
        n["switches"] = [sw.get(i, dict(servo=i, name="Switch %d" % (i + 1), state="off")) for i in range(n["servos"])]
        return n

    # ---------------------------------------------------------- nodes
    def add_node(self, host, name=None, servos=1, auto=False):
        host = host.strip().replace("http://", "").strip("/")
        with self.lock:
            for n in self.nodes:
                if n["host"].lower() == host.lower():
                    return n
            nid = "n%d" % (max([int(n["id"][1:]) for n in self.nodes] + [0]) + 1)
            n = self._fix(dict(id=nid, name=name or "ESP32 #%d" % (len(self.nodes) + 1), host=host, port=80, servos=servos, auto=auto))
            self.nodes.append(n)
            self.save()
            return n

    def remove_node(self, nid):
        with self.lock:
            self.nodes = [n for n in self.nodes if n["id"] != nid]
            self.net.pop(nid, None)
            self.save()

    def node(self, nid):
        return next((n for n in self.nodes if n["id"] == nid), None)

    def set_servo_count(self, nid, count):
        with self.lock:
            n = self.node(nid)
            if n:
                n["servos"] = max(1, min(4, int(count)))
                self._fix(n)
                self.save()

    def rename_node(self, nid, name):
        n = self.node(nid)
        if n and name.strip():
            n["name"] = name.strip()[:24]
            self.save()

    def rename_switch(self, nid, servo, name):
        n = self.node(nid)
        if n and name.strip():
            for s in n["switches"]:
                if s["servo"] == servo:
                    s["name"] = name.strip()[:24]
            self.save()

    def set_host(self, nid, host):
        n = self.node(nid)
        if n and host.strip():
            n["host"] = host.strip().replace("http://", "").strip("/")
            self.save()

    # ---------------------------------------------------------- switchboard helpers
    def all_switches(self):
        """-> list of (node, switch, label) in screen order."""
        out = []
        for n in self.nodes:
            for s in n["switches"]:
                out.append((n, s, "%s - %s" % (n["name"], s["name"])))
        return out

    def online(self, nid):
        return bool(self.net.get(nid, {}).get("online"))

    def ip_of(self, n):
        return self.net.get(n["id"], {}).get("ip") or n.get("ip") or n["host"]

    def switch_names(self):
        return [s["name"].lower() for _, s, _ in self.all_switches()]

    def resolve_phrase(self, phrase):
        """Voice: 'light', 'fan', 'lamp', 'switch', or a custom switch name -> (node, switch) or None."""
        p = (phrase or "").lower().strip()
        sw = self.all_switches()
        if not sw:
            return None
        for n, s, _ in sw:
            if p and (p in s["name"].lower() or s["name"].lower() in p):
                return n, s
        if p in GENERIC or not p:
            return sw[0][0], sw[0][1]
        return None

    # ---------------------------------------------------------- dispatch (asynchronous)
    def set_switch(self, nid, servo, on, cb=None):
        """Flick the servo. cb(ok, message, node, switch) is called on the UI thread."""
        n = self.node(nid)
        if n is None:
            if cb:
                self.post(lambda _: cb(False, "Unknown node", None, None), None)
            return
        sw = next((s for s in n["switches"] if s["servo"] == servo), None)
        if sw is None:
            if cb:
                self.post(lambda _: cb(False, "No such servo", n, None), None)
            return
        key = (nid, servo)
        if key in self.busy:
            if cb:
                self.post(lambda _: cb(False, "Still moving", n, sw), None)
            return
        self.busy.add(key)

        def work():
            ok, msg = False, "error"
            try:
                ok, msg = self.api.servo(n, servo, "on" if on else "off", self.cfg.ESP32_DEFAULT_ANGLE)
            except Exception as e:
                log.exception("switch failed")
                msg = str(e)[:50]
            finally:
                self.busy.discard(key)
            if ok:
                sw["state"] = "on" if on else "off"
                self.save()
                self.net.setdefault(nid, {}).update(online=True, last_seen=time.time())
            else:
                self.net.setdefault(nid, {}).update(online=False)
            self._log(n, sw, on, ok, msg)
            if cb:
                self.post(lambda _: cb(ok, msg, n, sw), None)
        threading.Thread(target=work, daemon=True, name="switch").start()

    def toggle(self, nid, servo, cb=None):
        n = self.node(nid)
        sw = next((s for s in n["switches"] if s["servo"] == servo), None) if n else None
        self.set_switch(nid, servo, not (sw and sw["state"] == "on"), cb)

    def _log(self, n, sw, on, ok, msg):
        try:
            os.makedirs(os.path.dirname(self.cfg.ESP32_LOG_FILE), exist_ok=True)
            with open(self.cfg.ESP32_LOG_FILE, "a") as f:
                f.write(json.dumps(dict(t=time.strftime("%Y-%m-%d %H:%M:%S"), node=n["name"], switch=sw["name"], action="on" if on else "off", ok=ok, msg=msg)) + "\n")
        except Exception:
            pass
        log.info("switch %s/%s -> %s : %s (%s)", n["name"], sw["name"], "ON" if on else "OFF", "OK" if ok else "FAILED", msg)

    # ---------------------------------------------------------- background health + discovery
    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="control").start()

    def stop(self):
        self.running = False

    def refresh_one(self, n):
        d = self.api.status(n)
        if d is None:
            self.net.setdefault(n["id"], {}).update(online=False)
            return False
        self.net[n["id"]] = dict(online=True, ip=d.get("ip"), rssi=d.get("rssi"), last_seen=time.time())
        for s in d.get("servos", []):
            for sw in n["switches"]:
                if sw["servo"] == s.get("id") and s.get("state") in ("on", "off"):
                    sw["state"] = s["state"]
        return True

    def _loop(self):
        last_disc = 0.0
        while self.running:
            try:
                for n in list(self.nodes):
                    self.refresh_one(n)
                if time.time() - last_disc > 60:
                    last_disc = time.time()
                    self.discover()
            except Exception:
                log.exception("control loop")
            for _ in range(int(self.cfg.ESP32_POLL_S * 5)):
                if not self.running:
                    return
                time.sleep(0.2)

    def discover(self):
        """Find the default mDNS node (esp32-switch.local) - and any _luna-switch._tcp service when zeroconf is installed."""
        found = []
        host = self.cfg.ESP32_MDNS_NAME
        if not any(n["host"].lower() == host.lower() for n in self.nodes):
            if self.api.resolve(host):
                d = self.api.info(dict(id="tmp", host=host, port=80))
                if d:
                    found.append((host, d))
        try:
            from zeroconf import ServiceBrowser, Zeroconf

            class L:
                def __init__(s):
                    s.items = []

                def add_service(s, zc, t, name):
                    info = zc.get_service_info(t, name)
                    if info and info.parsed_addresses():
                        s.items.append(info.parsed_addresses()[0])

                def update_service(s, *a):
                    pass

                def remove_service(s, *a):
                    pass
            zc, lis = Zeroconf(), L()
            ServiceBrowser(zc, "_luna-switch._tcp.local.", lis)
            time.sleep(2.0)
            zc.close()
            for ip in lis.items:
                if not any(n["host"] == ip or n.get("ip") == ip for n in self.nodes):
                    d = self.api.info(dict(id="tmp", host=ip, port=80))
                    if d:
                        found.append((ip, d))
        except Exception:
            pass
        for host, d in found:
            n = self.add_node(host, servos=int(d.get("servos", 1)), auto=True)
            n["ip"] = d.get("ip")
            self.save()
            log.info("discovered ESP32 node %s (%s)", n["name"], host)
            if self.on_found:
                self.post(self.on_found, n)
        return [h for h, _ in found]


# =============================================================================== screen
class ControlCenterScreen(Screen):
    name, title, accent = "control", "Control Center", (80, 210, 190)
    mini_pos = "br"

    def enter(self, tab="nodes", **kw):
        self.tab = tab
        self.lv = ListView(self.u)
        self.pending = set()
        self.msg, self.msg_until = "", 0.0
        self.reload()

    def resume(self):
        self.reload()

    # ---------------------------------------------------------------- rows
    def reload(self):
        cc = self.app.ctrl
        rows = []
        if self.tab == "nodes":
            for n in cc.nodes:
                on = cc.online(n["id"])
                rows.append(dict(label=n["name"], sub="%s   -   %d servo%s" % (cc.ip_of(n), n["servos"], "" if n["servos"] == 1 else "s"), icon="wifi",
                                 right="ONLINE" if on else "OFFLINE", rcol=GREEN if on else RED, tag=("node", n["id"]), col=self.accent))
            if not rows:
                rows.append(dict(label="No ESP32 paired yet", sub="Press + Add ESP32 (IP address or esp32-switch.local)", icon="wifi", tag=("none", None), col=MUTED))
        else:
            for n, s, label in cc.all_switches():
                on = cc.online(n["id"])
                rows.append(dict(label=label, sub="Servo %d   -   %s" % (s["servo"], "online" if on else "OFFLINE"), tag=("sw", n["id"], s["servo"]),
                                 col=GREEN if s["state"] == "on" else self.accent))
            if not rows:
                rows.append(dict(label="No switches yet", sub="Add an ESP32 on the Nodes tab", tag=("none", None), col=MUTED))
        self.lv.set_rows(rows, keep=True)

    def tick(self, dt):
        if int(time.time() * 2) % 4 == 0:
            self.reload()

    # ---------------------------------------------------------------- geometry
    def _tabs(self):
        u = self.u
        return {"nodes": pygame.Rect(int(30 * u), int(90 * u), int(220 * u), int(52 * u)),
                "board": pygame.Rect(int(262 * u), int(90 * u), int(240 * u), int(52 * u))}

    def _list_rect(self):
        u = self.u
        return pygame.Rect(int(30 * u), int(156 * u), int(self.w - 60 * u), int(self.h - 156 * u - 100 * u))

    def _add_rect(self):
        u = self.u
        return pygame.Rect(int(30 * u), int(self.h - 84 * u), int(300 * u), int(62 * u))

    # ---------------------------------------------------------------- draw
    @guarded("draw")
    def draw(self, surf):
        u = self.u
        surf.fill(BG)
        self.topbar(surf, "Control Center", right="%d node(s)" % len(self.app.ctrl.nodes))
        for k, r in self._tabs().items():
            act = (k == "nodes") == (self.tab == "nodes")
            button(surf, r, self.accent if act else MUTED, mix(CARD, self.accent, 0.35) if act else None)
            self.text(surf, "Nodes" if k == "nodes" else "Switchboard", r.centerx, r.centery - 11 * u, 21, TEXT, center=True)
        lr = self._list_rect()
        self.lv.draw(surf, lr, self.accent)
        if self.tab == "board":
            self._draw_pills(surf, lr)
        if self.tab == "nodes":
            ar = self._add_rect()
            button(surf, ar, GREEN)
            icon(surf, "plus", ar.left + 40 * u, ar.centery, 15 * u, GREEN)
            self.text(surf, "Add ESP32", ar.left + 76 * u, ar.centery - 12 * u, 22, TEXT)
        if time.time() < self.msg_until:
            self.text(surf, self.msg, self.w / 2 - 120 * u, self.h - 62 * u, 19, AMBER, center=True)

    def _draw_pills(self, surf, lr):
        u, lv = self.u, self.lv
        sw = self.app.ctrl.all_switches()
        for i, (n, s, _) in enumerate(sw):
            y = lr.top + i * lv.row_h - lv.scroll
            cell = pygame.Rect(lr.left, int(y), lr.width, int(lv.row_h - 8 * u))
            if cell.top < lr.top - 4 or cell.bottom > lr.bottom + 4:
                continue
            on = s["state"] == "on"
            busy = (n["id"], s["servo"]) in self.pending
            pill = pygame.Rect(cell.right - int(130 * u), cell.centery - int(20 * u), int(100 * u), int(40 * u))
            pygame.draw.rect(surf, mix(TRACK, GREEN, 0.7) if on else TRACK, pill, border_radius=int(20 * u))
            kx = pill.right - 20 * u if on else pill.left + 20 * u
            pygame.draw.circle(surf, AMBER if busy else TEXT, (int(kx), pill.centery), int(16 * u))
            lab = "..." if busy else ("ON" if on else "OFF")
            t = font(16 * u).render(lab, True, TEXT)
            surf.blit(t, (pill.left - t.get_width() - 12 * u, pill.centery - t.get_height() / 2))

    # ---------------------------------------------------------------- input
    def on_down(self, pos):
        self.lv.down(pos)
        self._down_pos = pos

    def on_move(self, pos):
        self.lv.move(pos)

    @guarded("on_up")
    def on_up(self, pos):
        for k, r in self._tabs().items():
            if inside(pos, r) and inside(getattr(self, "_down_pos", pos), r):
                self.lv.down_pos = None
                self.tab = k
                self.lv.scroll = 0
                self.reload()
                return
        if self.tab == "nodes" and inside(pos, self._add_rect()):
            self.lv.down_pos = None
            self.add_flow()
            return
        tag = self.lv.up(pos)
        if not tag or tag[0] == "none":
            return
        long = getattr(self.lv, "last_hold", 0) > 0.7
        if tag[0] == "node":
            self.node_menu(tag[1])
        elif tag[0] == "sw":
            if long:
                self.switch_menu(tag[1], tag[2])
            else:
                self.toggle(tag[1], tag[2])

    # ---------------------------------------------------------------- actions
    def say_msg(self, text, secs=3.5):
        self.msg, self.msg_until = text, time.time() + secs

    def toggle(self, nid, servo):
        a = self.app
        if (nid, servo) in self.pending:
            return
        self.pending.add((nid, servo))

        def done(ok, msg, n, sw):
            self.pending.discard((nid, servo))
            self.reload()
            if ok:
                self.say_msg("%s - %s: %s" % (n["name"], sw["name"], sw["state"].upper()))
            else:
                self.say_msg("Could not switch: %s" % msg)
        a.ctrl.toggle(nid, servo, done)

    def add_flow(self):
        a = self.app

        def got_host(host):
            if not host or not host.strip():
                return

            def got_name(name):
                n = a.ctrl.add_node(host, name=(name or "").strip() or None)
                self.say_msg("Checking %s ..." % n["name"])

                def work():
                    d = a.ctrl.api.info(n)
                    return d

                def done(d):
                    if d:
                        a.ctrl.set_servo_count(n["id"], int(d.get("servos", n["servos"])))
                        a.ctrl.refresh_one(n)
                        self.say_msg("%s is online (%d servos)" % (n["name"], n["servos"]))
                    else:
                        self.say_msg("Saved, but %s did not answer yet" % n["name"], 5)
                    self.reload()
                a.run_bg(work, done)
                self.reload()
            a.ask_text("Name for this ESP32", "ESP32 #%d" % (len(a.ctrl.nodes) + 1), got_name, hint="for example: Bedroom switches")
        a.ask_text("ESP32 address", a.cfg.ESP32_MDNS_NAME, got_host, hint="IP address (192.168.1.50) or esp32-switch.local")

    def node_menu(self, nid):
        a, cc = self.app, self.app.ctrl
        n = cc.node(nid)
        if not n:
            return

        def count():
            a.choose("How many MG90 servos on %s?" % n["name"], [("%d servo%s" % (k, "" if k == 1 else "s"), "", (lambda kk=k: self._set_count(nid, kk)), self.accent) for k in (1, 2, 3, 4)], self.accent)

        def test():
            self.say_msg("Testing ...")
            a.run_bg(lambda: cc.refresh_one(n), lambda ok: (self.say_msg("Online" if ok else "No answer from %s" % cc.ip_of(n)), self.reload()))

        a.choose(n["name"], [
            ("Test connection", cc.ip_of(n), test, GREEN),
            ("Servos connected: %d" % n["servos"], "Choose 1 to 4", count, BLUE),
            ("Rename", "", lambda: a.ask_text("New name", n["name"], lambda t: (cc.rename_node(nid, t), self.reload()) if t else None), AMBER),
            ("Change address", n["host"], lambda: a.ask_text("ESP32 address", n["host"], lambda t: (cc.set_host(nid, t), self.reload()) if t else None), AMBER),
            ("Remove this ESP32", "", lambda: a.confirm("Remove %s?" % n["name"], lambda: (cc.remove_node(nid), self.reload()), "Remove", danger=True), RED)], self.accent)

    def _set_count(self, nid, k):
        self.app.ctrl.set_servo_count(nid, k)
        self.reload()
        self.say_msg("Servos set to %d" % k)

    def switch_menu(self, nid, servo):
        a, cc = self.app, self.app.ctrl
        n = cc.node(nid)
        s = next(x for x in n["switches"] if x["servo"] == servo)
        a.choose("%s - %s" % (n["name"], s["name"]), [
            ("Rename switch", "e.g. Light, Fan, Lamp - Luna uses the name by voice",
             lambda: a.ask_text("Switch name", s["name"], lambda t: (cc.rename_switch(nid, servo, t), self.reload()) if t else None), AMBER),
            ("Toggle now", "", lambda: self.toggle(nid, servo), GREEN)], self.accent)

    def context(self):
        return "The Control Center on the %s tab, with %d ESP32 node(s)." % ("switchboard" if self.tab == "board" else "nodes", len(self.app.ctrl.nodes))

    def comment(self):
        return "Tap a switch to flick it, or say, Luna, turn on the light."

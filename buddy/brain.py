"""
The brain: turns what you said into a Reply (text + emotion + optional action).
Offline  -> built-in rule-based intents (always works).
Online   -> unknown questions go to Claude if ANTHROPIC_API_KEY is set.
"""
import logging
import random
import re
import time
from datetime import date
from dataclasses import dataclass
from typing import Optional

from .util import time_greeting

log = logging.getLogger("brain")


@dataclass
class Reply:
    text: str
    emotion: str = "happy"
    action: Optional[str] = None      # analysis | exit:<target> | sleep | wake | volume:+10 | timer:<sec>


JOKES = [
    "Why did the robot go on vacation? To recharge its batteries!",
    "Why do programmers prefer dark mode? Because light attracts bugs!",
    "I told my Wi-Fi it was special. Now it feels connected!",
    "Why was the transistor so calm? It had no resistance to change!",
    "What do you call a robot who loves to dance? A boogie bot!",
    "Why did the sensor break up with the circuit? It felt no connection!",
]

NUMS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen".split())}
NUMS.update({"a": 1, "an": 1, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
             "seventy": 70, "eighty": 80, "ninety": 90})


NAME_STOP = set("""fine good great okay ok tired sad happy hungry bored back here there sure not very going leaving ready
busy sleepy angry late home done new awesome cool nice fun amazing wonderful beautiful perfect funny crazy mad sorry
confused scared excited lost thirsty hot cold sick alone wrong right correct yes no it that this the a an me you luna
camera picture photo selfie image gallery""".split())


def valid_name(n):
    parts = n.split()
    return 1 <= len(parts) <= 2 and all(p.isalpha() and 2 <= len(p) <= 20 and p not in NAME_STOP for p in parts)


def parse_name(t, allow_bare=False):
    """Pull a person's name out of 'this is Rahul' / 'my name is Rahul' / 'I am Rahul' (and a bare name if allow_bare)."""
    pats = [r"\b(?:this is|meet|say hello to|say hi to|introduce yourself to|remember (?:him|her|them) as|that is|here is) ([a-z]+(?: [a-z]+)?)$",
            r"\b(?:my name is|call me|i am called|remember my face as|remember me as|my name's) ([a-z]+(?: [a-z]+)?)$",
            r"\b(?:i am|i'm|im|it is|it's) ([a-z]+)$"]
    for p in pats:
        m = re.search(p, t)
        if m and valid_name(m.group(1)):
            return m.group(1)
    if allow_bare and valid_name(t):
        return t
    return None


TIER_WORDS = [("high priority", "priority1"), ("top priority", "priority1"), ("priority one", "priority1"), ("priority 1", "priority1"),
              ("normal priority", "priority2"), ("priority two", "priority2"), ("priority 2", "priority2"),
              ("least priority", "least"), ("lowest priority", "least"), ("master", "master"), ("priority", "priority2"), ("guest", "least")]


def norm(text):
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower()).strip()


def words_to_int(words):
    total, seen = 0, False
    for w in words:
        if w.isdigit():
            total += int(w)
            seen = True
        elif w in NUMS:
            total += NUMS[w]
            seen = True
        elif w == "hundred":
            total *= 100
    return total if seen else None


def system_command(t):
    """'switch to raspberry pi / os / calibration / desktop' (no wake word needed)."""
    if re.search(r"\b(switch|go|change|exit|back)\b.*\b(raspberry|rasp|berry|pi|pie|os|o s|operating system|desktop|calibration|calibrate)\b", t) \
            or re.search(r"\b(exit|quit|close)\b.*\b(robot|assistant|luna)( mode)?\b", t):
        if re.search(r"calibrat", t):
            return "calibration"
        return "os"
    return None


def strip_wake(t, wake_words):
    for w in sorted(wake_words, key=len, reverse=True):
        m = re.search(r"\b(hey |hi |hello |ok |okay )?%s\b" % re.escape(w), t)
        if m:
            return True, (t[:m.start()] + " " + t[m.end():]).strip()
    return False, t


class Brain:
    def __init__(self, cfg, get_snapshot, is_online, known_names=lambda: []):
        self.cfg, self.snap, self.is_online = cfg, get_snapshot, is_online
        self.known_names = lambda: [n.lower() for n in known_names()]
        self.history = []
        self.who = cfg.OWNER_NAME
        self.person = None
        self.screen_ctx = ""
        self.screen_comment = ""
        self.switch_names = lambda: []        # set by the app: names of the ESP32 switches (for "turn on the fan")

    # ------------------------------------------------------------ helpers
    def summary(self):
        s = self.snap()
        parts = []
        if s["temperature"] is not None:
            parts.append("Temperature is %.0f degrees Celsius" % s["temperature"])
        if s["humidity"] is not None:
            parts.append("humidity is %.0f percent" % s["humidity"])
        if s["pressure"] is not None:
            parts.append("air pressure is %.0f hectopascals" % s["pressure"])
        parts.append("air quality is %s" % s["aq_label"].lower())
        txt = ", ".join(parts) + "."
        if s["comfort"] not in ("No data", "Comfortable"):
            txt += " The room feels %s." % s["comfort"].lower()
        elif s["comfort"] == "Comfortable":
            txt += " The room feels comfortable."
        return txt

    def _has(self, t, *pats):
        return any(re.search(p, t) for p in pats)

    # ------------------------------------------------------------- handle
    def handle(self, t, person=None):
        self.who = (person or {}).get("name") or self.cfg.OWNER_NAME
        self.person = person
        r = self._rules(t)
        if r is not None and r.action == "comment":
            if self.is_online() and self.cfg.ANTHROPIC_API_KEY:
                l = self._llm("The user asks you about what they are doing on the screen: " + t)
                if l:
                    return l
            return Reply(self.screen_comment or "I am right here with you. Tell me what you would like to do.", "happy")
        if r is not None:
            return r
        if self.is_online() and self.cfg.ANTHROPIC_API_KEY:
            r = self._llm(t)
            if r:
                return r
        return Reply(random.choice([
            "Sorry, I did not catch that. Can you say it again?",
            "Hmm, I am not sure about that one. Try asking about the room, the time, or a joke.",
        ]), "confused")

    def _rules(self, t):
        s = self.snap()
        has = lambda *p: self._has(t, *p)
        c = self.cfg
        dev = c.DEVELOPER_NAME.lower()
        if self._comment_intent(t):
            return Reply("", "thinking", "comment")
        r = self._apps(t, has)
        if r:
            return r
        r = self._people_and_photos(t, has)
        if r:
            return r
        r = self._identity(t, has)
        if r:
            return r
        if has(r"\b(room|environment|surroundings?)\b.*\b(condition|status|report|state|analysis)\b",
               r"\b(condition|status|report)\b.*\broom\b", r"\banaly[sz]\w*\b",
               r"\bhow is the room\b", r"\b(show|display)\b.*\b(readings?|sensors?|dashboard)\b"):
            return Reply("Here is the room analysis.", "happy", "analysis")
        if has(r"\btemperature\b", r"\bhow (hot|cold|warm)\b"):
            if s["temperature"] is None:
                return Reply("My temperature sensor is not giving me a reading right now.", "sad")
            return Reply("It is %.0f degrees Celsius in here." % s["temperature"],
                         "hot" if s["temperature"] >= self.cfg.HOT_C else "cold" if s["temperature"] <= self.cfg.COLD_C else "happy")
        if has(r"\bhumidity\b", r"\bhumid\b"):
            if s["humidity"] is None:
                return Reply("I cannot read the humidity right now.", "sad")
            return Reply("Humidity is %.0f percent." % s["humidity"], "happy")
        if has(r"\b(air )?pressure\b", r"\bbarometer\b"):
            if s["pressure"] is None:
                return Reply("I do not have a pressure reading. I need a pressure sensor or the internet.", "confused")
            return Reply("Air pressure is %.0f hectopascals." % s["pressure"], "happy")
        if has(r"\bair quality\b", r"\bgas\b", r"\bsmoke\b", r"\bis the air\b", r"\bbreathe\b"):
            e = "alert" if s["gas_alert"] else "happy"
            return Reply("Air quality is %s." % s["aq_label"].lower(), e)
        if has(r"\bwhat('s| is)? (the )?time\b", r"\bwhat time\b", r"\btime now\b"):
            return Reply("It is %s." % time.strftime("%I:%M %p").lstrip("0"), "happy")
        if has(r"\b(what('s| is)? )?(the )?(date|day)( today)?\b") and has(r"\bdate\b|\bwhat day\b|\btoday\b"):
            return Reply("Today is %s." % time.strftime("%A, %d %B %Y"), "happy")
        m = re.search(r"\btimer\b.*?(?:for )?([a-z0-9 ]+?) (second|minute|hour)s?\b", t) or \
            re.search(r"\b(?:for )?([a-z0-9 ]+?) (second|minute|hour)s? timer\b", t)
        if m:
            n = words_to_int(m.group(1).split())
            if n:
                sec = n * {"second": 1, "minute": 60, "hour": 3600}[m.group(2)]
                return Reply("Okay, timer set for %d %s%s." % (n, m.group(2), "" if n == 1 else "s"),
                             "happy", "timer:%d" % sec)
        if has(r"\b(go to sleep|sleep now|good night|goodnight)\b"):
            return Reply("Good night! Touch me or say my name to wake me up.", "sleepy", "sleep")
        if has(r"\bwake up\b"):
            return Reply("I am awake!", "surprised", "wake")
        if has(r"\b(volume up|louder|speak up)\b"):
            return Reply("Okay, louder.", "happy", "volume:+10")
        if has(r"\b(volume down|quieter|softer|lower the volume)\b"):
            return Reply("Okay, quieter.", "happy", "volume:-10")
        if has(r"\bhow are you\b", r"\bhow('s| is) it going\b"):
            return Reply(random.choice(["I am great, thanks for asking!", "Feeling happy and fully charged!"]), "happy")
        if has(r"\bjoke\b", r"\bmake me laugh\b"):
            return Reply(random.choice(JOKES), "joy")
        if has(r"\bi love you\b", r"\byou are (the best|awesome|cute|great)\b"):
            return Reply("Aww, I love you too, %s!" % self.who, "love")
        if has(r"\b(thank you|thanks)\b"):
            return Reply("You are welcome!", "happy")
        if has(r"\bgood (morning|afternoon|evening)\b"):
            return Reply("%s, %s! How can I help?" % (time_greeting(), self.who), "happy")
        if has(r"\b(hello|hi|hey|hai)\b"):
            return Reply("%s, %s! How can I help?" % (time_greeting(), self.who), "happy")
        if has(r"\b(are you online|internet|wi ?fi|connected)\b"):
            return Reply("I am online and can use my smart voice." if self.is_online()
                         else "I am offline right now, but I still work with built in skills.", "happy" if self.is_online() else "thinking")
        if has(r"\bwhat can you do\b", r"\bhelp\b", r"\bcommands?\b"):
            return Reply("I can tell you the room condition, temperature, humidity, pressure and air quality, "
                         "the time, set timers, tell jokes, and chat. Say switch to Raspberry Pi to go to the desktop.", "happy")
        return None

    # ------------------------------------------------------------ apps / music / security
    def _secs(self, t, default=10):
        m = re.search(r"(\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|forty|fifty|sixty)\s*(?:more )?(?:second|seconds|sec)?", t)
        n = words_to_int(m.group(1).split()) if m else None
        return n or default

    def _docs_usb(self, t, has):
        usb = r"(usb|pen ?drive|pendrive|flash drive|thumb drive|external (?:drive|storage)|memory stick)"
        if has(r"\b(eject|safely remove|unmount|remove)\b.*\b%s\b" % usb):
            return Reply("Ejecting the USB drive.", "happy", "usb:eject")
        if has(r"\b(back ?up|copy|save)\b.*\b(to|on|onto)\b.*\b%s\b" % usb, r"\bback ?up (my )?(photos|pictures|gallery|drawings)\b"):
            return Reply("Backing up to the USB drive.", "happy", "usb:backup")
        if has(r"\b(stop|pause|quit)\b.*\breading\b", r"\bstop (talking|speaking)\b", r"^be quiet$"):
            return Reply("", "happy", "pdfctl:stopread")
        if has(r"\b(continue|resume|keep) reading\b"):
            return Reply("", "happy", "pdfctl:read")
        m = re.search(r"\b(?:go to|open|jump to|show|turn to)\s+page\s+(\w+(?: \w+)?)$", t) or re.search(r"^page\s+(\w+(?: \w+)?)$", t)
        if m:
            n = int(m.group(1)) if m.group(1).isdigit() else words_to_int(m.group(1).split())
            if n:
                return Reply("", "happy", "pdfctl:page:%d" % n)
        if has(r"\bnext page\b", r"\bturn the page\b"):
            return Reply("", "happy", "pdfctl:next")
        if has(r"\b(previous|last|back) page\b"):
            return Reply("", "happy", "pdfctl:prev")
        if has(r"\b(zoom in|bigger|enlarge|magnify)\b"):
            return Reply("", "happy", "pdfctl:zin")
        if has(r"\b(zoom out|smaller|shrink)\b"):
            return Reply("", "happy", "pdfctl:zout")
        m = re.search(r"\b(?:read|open|show|display)\b\s+(?:me\s+)?(?:the\s+|my\s+|a\s+)?(?:pdf|document|book|file)(?:\s+(?:called|named))?\s+(.+)$", t)
        if m and not re.match(r"^(page|number|library|list|folder)\b", m.group(1)):
            return Reply("", "happy", "pdf:" + m.group(1).strip())
        if has(r"\bread (this|the|it|aloud|out loud|to me|page|document|pdf)\b", r"\bstart reading\b", r"^read$", r"\bread (it )?aloud\b"):
            return Reply("", "happy", "pdfctl:read")
        if has(r"\b(open|show|browse|access|check|list|look (?:at|in)|what is on|what's on)\b.*\b%s\b" % usb):
            return Reply("Opening the USB drive.", "happy", "open:usb")
        if has(r"\b(open|show|go to|browse|read)\b.*\b(documents|pdfs|pdf files|pdf library|my books|files)\b", r"^(open )?(a )?pdf$"):
            return Reply("Opening your documents.", "happy", "open:documents")
        return None

    # ------------------------------------------------------------ v2: ESP32 switches + calendar
    SWITCH_WORDS = r"light|lights|lamp|lamps|bulb|tubelight|tube light|fan|switch|switches|heater|tv|television|plug|socket"

    def _home(self, t, has):
        verb = r"(?:turn|switch|put|power|flip)"
        m = re.search(r"\b%s\s+(on|off)\s+(?:the |my |a |an )?(.+)$" % verb, t) or \
            re.search(r"\b%s\s+(?:the |my |a |an )?(.+?)\s+(on|off)$" % verb, t)
        if m:
            a, b = m.group(1), m.group(2)
            state, target = (a, b) if a in ("on", "off") else (b, a)
            names = [n for n in self.switch_names() if n and not re.fullmatch(r"switch \d", n)]
            hit = next((n for n in names if n in target), None)
            if not hit:
                w = re.search(r"\b(%s)\b" % self.SWITCH_WORDS, target)
                hit = w.group(1) if w else None
            if hit:
                return Reply("", "happy", "switch:%s:%s" % (state, hit))
        if has(r"\b(light|lights|lamp|fan)\b.*\b(on|off)\b", r"\b(on|off)\b.*\b(the )?(light|lights|lamp|fan)\b") and has(r"\b(please|can you|could you|luna)\b|^(turn|switch)"):
            state = "off" if re.search(r"\boff\b", t) else "on"
            w = re.search(r"\b(light|lights|lamp|fan)\b", t)
            return Reply("", "happy", "switch:%s:%s" % (state, w.group(1)))
        # calendar questions
        if has(r"\b(calendar|events?|birthdays?|anniversar(?:y|ies)|reminders?|schedule)\b") and has(r"\b(what|any|do i have|tell me|read|check|is there)\b"):
            if has(r"\btomorrow\b"):
                return Reply("", "happy", "calendar:tomorrow")
            if has(r"\btoday\b"):
                return Reply("", "happy", "calendar:today")
            return Reply("", "happy", "calendar:upcoming")
        return None

    def _apps(self, t, has):
        r = self._home(t, has)
        if r:
            return r
        r = self._docs_usb(t, has)
        if r:
            return r
        if has(r"\b(stop|silence|turn off|switch off)\b.*\b(alarm|siren)\b"):
            return Reply("Stopping the alarm.", "happy", "alarm:stop")
        if has(r"\b(turn off|switch off|disable|deactivate|stop)\b.*\bsecurity\b"):
            return Reply("Okay, turning security mode off.", "happy", "security:off")
        if has(r"\b(turn on|switch on|enable|activate|start)\b.*\bsecurity\b", r"\bsecurity mode on\b"):
            return Reply("Security mode on. I am on guard.", "happy", "security:on")
        if has(r"\b(stop|end|finish)\b.*\brecording\b"):
            return Reply("Stopping the recording.", "happy", "record:stop")
        if has(r"\b(start|begin)\b.*\b(recording|video)\b", r"\brecord (a |the )?(video|clip)\b", r"\btake a video\b", r"\bfilm (me|this|us)\b"):
            return Reply("Recording a video.", "happy", "record:start")
        m = re.search(r"\b(?:create|make|add|new)\\b.*\\balbum\\b(?: called| named)?\s+([a-z ]+)$", t) if False else re.search(r"\b(?:create|make|add)\b.*\balbum\b (?:called |named )?([a-z0-9 ]+)$", t)
        if m and m.group(1).strip() not in ("", "album"):
            return Reply("Creating the album %s." % m.group(1).strip().title(), "happy", "album:" + m.group(1).strip())
        # --- playback control
        if has(r"\b(rewind|go back|skip back|back)\b.*\b(second|seconds|sec)\b", r"^rewind\b"):
            return Reply("Rewinding.", "happy", "mctl:back:%d" % self._secs(t))
        if has(r"\b(forward|fast forward|skip ahead|jump ahead|skip forward)\b"):
            return Reply("Skipping ahead.", "happy", "mctl:fwd:%d" % self._secs(t))
        if has(r"^(please )?pause\b", r"\bpause (the )?(song|music|video|movie|playback|it)\b", r"\bhold on the (song|music)\b"):
            return Reply("Paused.", "happy", "mctl:pause")
        if has(r"^(resume|continue|unpause|keep playing)\b", r"\b(resume|continue) (the )?(song|music|video|movie|playing|playback)\b", r"^play$"):
            return Reply("Resuming.", "happy", "mctl:resume")
        if has(r"\b(next|skip)\b( song| track| one)?$", r"\bplay (the )?next\b", r"\bnext (song|track)\b", r"^skip\b"):
            return Reply("Next song.", "happy", "mctl:next")
        if has(r"\b(previous|last) (song|track|one)\b", r"\bplay (the )?previous\b", r"\bgo back a song\b"):
            return Reply("Previous song.", "happy", "mctl:prev")
        if has(r"\b(stop|end|turn off|switch off)\b.*\b(music|song|songs|playing|playback|video|movie)\b", r"^stop$"):
            return Reply("Stopped.", "happy", "mctl:stop")
        if has(r"\bshuffle\b"):
            off = has(r"\b(off|stop|disable|no)\b")
            return Reply("Shuffle off." if off else "Shuffle on.", "happy", "mctl:shuffle:" + ("off" if off else "on"))
        if has(r"\b(loop|looping|repeat|repeating)\b"):
            if has(r"\b(off|stop|stopping|disable|no more|turn off)\b"):
                return Reply("Loop off.", "happy", "mctl:loop:off")
            return Reply("Looping.", "happy", "mctl:loop:" + ("all" if has(r"\b(album|playlist|all|everything)\b") else "one"))
        # --- play something
        m = re.match(r"^(?:please )?(?:can you |could you |will you )?(?:play|put on|start playing|i want to (?:hear|listen to)|let me (?:hear|listen to))\s+(.+)$", t)
        if m:
            rest = m.group(1).strip()
            mv = re.match(r"^(?:the |a |my )?(?:last |latest |recent |newest )?(?:movie|film|video)s?\b\s*(.*)$", rest)
            if mv:
                latest = bool(re.match(r"^(?:the |a |my )?(?:last|latest|recent|newest)\b", rest))
                return Reply("", "happy", "movie:" + ("latest" if latest else mv.group(1).strip()))
            return Reply("", "happy", "music:" + rest)
        # --- opening apps
        if has(r"\b(go back|back)$", r"\bgo to the previous (screen|page)\b"):
            return Reply("Going back.", "happy", "back")
        if has(r"\b(go (to )?home|robot mode|show (me )?your face|close (the )?(menu|app|settings|music|movies|camera|drawing|everything)|exit (the )?(menu|app))\b"):
            return Reply("Back to robot mode.", "happy", "home")
        m = re.search(r"\b(?:open|show|go to|launch|start|take me to|display)\b\s+(?:me )?(?:the |my |a )?(.*)$", t)
        if m and not re.search(r"\b(image|picture|photo|pic|gallery|album|hidden|private|secret)\b", m.group(1)):
            what = m.group(1)
            for pat, target, say in ((r"\broom analysis\b|\banalysis\b", "analysis", "Opening room analysis."), (r"\b(display|brightness)\b(?! the room)", "display", "Opening display settings."), (r"\bsettings?\b", "settings", "Opening settings."),
                                     (r"\bmenu\b", "menu", "Here is the menu."), (r"\b(music|songs?|albums?|playlist)\b", "music", "Opening music."),
                                     (r"\b(movies?|videos?|films?)\b", "movies", "Opening movies."), (r"\bcamera\b", "camera", "Opening the camera."),
                                     (r"\b(drawing|whiteboard|paint|sketch)\b", "drawing", "Opening drawing."), (r"\babout\b", "about", "Opening about."),
                                     (r"\bwi-?fi\b", "wifi", "Opening Wi-Fi."), (r"\bbluetooth\b", "bluetooth", "Opening Bluetooth."),
                                     (r"\bsecurity\b", "security", "Opening security."),
                                     (r"\bcalendar\b", "calendar", "Opening the calendar."),
                                     (r"\b(control cent(?:er|re)|switch ?board|smart home|home control)\b", "control", "Opening the control center."),
                                     (r"\bprivacy\b", "privacy", "Opening privacy. Please type the PIN.")):
                if re.search(pat, what):
                    return Reply(say, "happy", "open:" + target)
        return None

    def _comment_intent(self, t):
        return bool(re.search(r"\bwhat (am i|are we) doing\b|\bwhat do you (think|see)\b|\b(any|some|give me( a)?) (suggestion|suggestions|idea|ideas|tip|tips|advice)\b|"
                              r"\bsuggest\b|\bcomment on\b|\bhow (does|do) (it|this) look\b|\bwhat should i (do|draw|play|watch|listen|try)\b|\bwhat is (on )?(my|the) screen\b", t))

    # ------------------------------------------------- people, photos, gallery
    def _people_and_photos(self, t, has):
        # --- introductions
        n = parse_name(t)
        if n:
            return Reply("", "happy", "introduce:" + n)
        # --- priority / people management is MANUAL only (Settings > Privacy)
        tier_alt = "|".join(re.escape(w) for w, _ in TIER_WORDS)
        if re.search(r"\b(?:make|set|promote|demote|move)\s+[a-z]+(?: [a-z]+)??\s+(?:(?:as|to|into)\s+)?(?:(?:a|an|the)\s+)?(?:%s)\b" % tier_alt, t) \
                or re.search(r"\brename [a-z]+", t) or re.search(r"\b(?:forget|remove) ([a-z]+)", t) and re.search(r"\b(?:forget|remove) ([a-z]+)", t).group(1) in self.known_names():
            return Reply("Priority levels and people are managed by hand. Open the menu, then Settings, then Privacy.", "confused")
        if has(r"\bwho am i\b", r"\bdo you (know|recogni[sz]e|remember) me\b", r"\bwhat is my name\b"):
            return Reply("", "happy", "whoami")
        if has(r"\bwho (is|are) (in front|here|there|around|with me)\b", r"\bwho (can|do) you see\b"):
            return Reply("", "happy", "who_visible")
        if has(r"\bwho do you know\b", r"\b(list|name) (all )?(the )?(people|faces|friends)\b", r"\bhow many (people|faces)\b"):
            return Reply("", "happy", "list_people")
        # --- hidden gallery / pin
        if has(r"\b(change|reset|set|create|new)\b.*\b(pin|passcode|password)\b"):
            return Reply("Okay, please use the keypad on the screen.", "happy", "change_pin")
        if has(r"\b(hidden|private|secret|locked|vault)\b.*\b(gallery|galary|album|pictures|photos|folder|library)\b", r"\bopen (the )?vault\b"):
            return Reply("Please type your PIN on the screen.", "happy", "hidden_gallery")
        # --- gallery
        if has(r"\b(close|exit|leave)\b.*\b(gallery|galary|album|library)\b", r"\bgo back to (robot|luna)\b"):
            return Reply("Okay, back to robot mode.", "happy", "close_gallery")
        if has(r"\b(open|show|display|go to|see|view)\b.*\b(gallery|galary|album|library|pictures|photos|images)\b"):
            return Reply("Opening the gallery.", "happy", "gallery")
        # --- taking pictures
        if has(r"\bgroup (photo|picture|pic|selfie|shot)\b"):
            return Reply("Everyone squeeze in! Look at the camera.", "joy", "photo:group")
        if has(r"\bselfie\b"):
            return Reply("Lets take a selfie! Smile!", "joy", "photo:selfie")
        if has(r"\b(capture|take|click|snap|shoot|grab)\b.*\b(picture|photo|pic|image|snap)\b", r"\bsay cheese\b", r"\b(capture|snap)\b$"):
            return Reply("Say cheese!", "joy", "photo:picture")
        if has(r"\b(show|display|view|see)\b.*\b(image|picture|photo|pic)\b"):
            return Reply("Here is the picture.", "happy", "show_image")
        return None

    # ------------------------------------------------------------- identity
    def developer_age(self):
        y, m, d = self.cfg.DEVELOPER_DOB
        today = date.today()
        return today.year - y - ((today.month, today.day) < (m, d))

    def about_developer(self):
        c = self.cfg
        y, m, d = c.DEVELOPER_DOB
        born = date(y, m, d).strftime("%d %B %Y").lstrip("0")
        return ("%s is my developer and creator. He was born on %s, so he is %d years old. "
                "He is studying %s at %s, and he will graduate in %d. "
                "He loves %s. He built me with a Raspberry Pi, sensors, and a lot of love."
                % (c.DEVELOPER_NAME, born, self.developer_age(), c.DEVELOPER_COURSE,
                   c.DEVELOPER_COLLEGE, c.DEVELOPER_GRAD_YEAR, c.DEVELOPER_INTERESTS))

    def _identity(self, t, has):
        c, dev = self.cfg, self.cfg.DEVELOPER_NAME.lower()
        if has(r"\bwall[ -]?e\b", r"\bwalle\b"):
            return Reply("No, I am %s, not WALL-E! WALL-E is a different robot. I am %s, a desk assistant pet robot built by %s."
                         % (c.ROBOT_NAME, c.ROBOT_NAME, c.DEVELOPER_NAME), "joy")
        if has(r"\b(born|birthday|birth ?date|date of birth)\b.*\b%s\b" % dev, r"\b%s\b.*\b(born|birthday|birth ?date)\b" % dev,
               r"\bwhen (was|is) (my |your )?(developer|creator|maker)\b.*\bborn\b"):
            y, m, d = c.DEVELOPER_DOB
            return Reply("%s was born on %s." % (c.DEVELOPER_NAME, date(y, m, d).strftime("%d %B %Y").lstrip("0")), "happy")
        if has(r"\bhow old\b.*\b(%s|developer|creator|maker)\b" % dev, r"\b%s'?s? age\b" % dev):
            return Reply("%s is %d years old." % (c.DEVELOPER_NAME, self.developer_age()), "happy")
        if has(r"\b(where|which (college|university))\b.*\b(%s|developer|creator|maker)\b.*\b(study|studies|studying|college|learn)\b" % dev,
               r"\b%s'?s? (college|university)\b" % dev, r"\b(college|university)\b.*\b%s\b" % dev):
            return Reply("%s studies at %s." % (c.DEVELOPER_NAME, c.DEVELOPER_COLLEGE), "happy")
        if has(r"\bwhat\b.*\b(%s|developer|creator|maker)\b.*\b(study|studies|studying|course|branch|degree)\b" % dev,
               r"\b%s'?s? (course|branch|degree)\b" % dev):
            return Reply("%s is studying %s." % (c.DEVELOPER_NAME, c.DEVELOPER_COURSE), "happy")
        if has(r"\b%s\b" % dev, r"\b(developer|creator|maker|inventor|programmer)\b",
               r"\bwho (made|built|created|developed|designed|programmed) you\b", r"\byour (dad|father|owner)\b"):
            return Reply(self.about_developer(), "love")
        if has(r"\b(who are you|what are you|your name|what is your name|what's your name|introduce yourself|"
               r"tell me about (yourself|you)|about yourself)\b"):
            return Reply("Hi! I am %s, not WALL-E! I am a friendly desk assistant pet robot, created by %s, a mechatronics engineering student. "
                         "I live on your desk, show feelings on my face, listen to you, and keep an eye on the room's temperature, humidity, "
                         "air pressure and air quality. Say my name to chat with me!" % (c.ROBOT_NAME, c.DEVELOPER_NAME), "happy")
        return None

    # ---------------------------------------------------------------- LLM
    def _llm(self, text):
        try:
            import requests
            s = self.snap()
            ctx = ("You are talking to %s. " % self.who if self.person else "") + ("What is on the screen right now: %s " % self.screen_ctx if self.screen_ctx else "") + "Room now: temp=%s C, humidity=%s %%, pressure=%s hPa, air quality=%s." % (
                s["temperature"], s["humidity"], s["pressure"], s["aq_label"])
            system = ("You are %s (never WALL-E), a cute friendly desk pet robot with a face on a small screen, "
                      "created by %s. " % (self.cfg.ROBOT_NAME, self.cfg.DEVELOPER_NAME)
                      + self.about_developer() + " "
                      + "Reply in at most two short spoken sentences, no markdown, no emojis. "
                        "Begin with exactly one emotion tag in square brackets chosen from: "
                        "happy, sad, surprised, love, thinking, neutral, angry, joy. " + ctx)
            msgs = self.history[-6:] + [{"role": "user", "content": text}]
            r = requests.post("https://api.anthropic.com/v1/messages",
                              headers={"x-api-key": self.cfg.ANTHROPIC_API_KEY,
                                       "anthropic-version": "2023-06-01",
                                       "content-type": "application/json"},
                              json={"model": self.cfg.LLM_MODEL, "max_tokens": 120,
                                    "system": system, "messages": msgs},
                              timeout=self.cfg.LLM_TIMEOUT_S)
            r.raise_for_status()
            out = r.json()["content"][0]["text"].strip()
            m = re.match(r"^\[(\w+)\]\s*(.*)$", out, re.S)
            emo, spoken = (m.group(1).lower(), m.group(2)) if m else ("happy", out)
            if emo not in ("happy", "sad", "surprised", "love", "thinking", "neutral", "angry", "joy"):
                emo = "happy"
            self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": spoken}]
            self.history = self.history[-12:]
            return Reply(spoken, emo)
        except Exception as e:
            log.info("online brain failed: %s", e)
            return None

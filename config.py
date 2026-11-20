"""
Desk Buddy - configuration
==========================
Edit this file, or (better) create `config_local.py` next to it and put only
the values you want to override there. config_local.py is never overwritten.
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")

# ----------------------------------------------------------------- identity
# Facts Luna knows about her developer (edit freely; used for "tell me about Koushik")
DEVELOPER_NAME = "Koushik"
DEVELOPER_DOB = (2004, 11, 2)                      # year, month, day
DEVELOPER_COURSE = "BE in Mechatronics Engineering"
DEVELOPER_COLLEGE = "The Oxford College of Engineering, Bangalore"
DEVELOPER_GRAD_YEAR = 2027
DEVELOPER_INTERESTS = "robotics, embedded systems and CAD"
ROBOT_NAME = "Luna"
WAKE_WORDS = ("luna", "loona")   # say "Luna, what is the time?"
REQUIRE_WAKE_WORD = True         # "switch to ..." commands never need the wake word
FOLLOWUP_WINDOW_S = 7            # after a reply you can talk without the wake word

# ---------------------------------------------------------------- GPIO pins
# BCM numbers (NOT physical pin numbers)
DHT_GPIO = 4                     # DHT22 data     -> physical pin 7
TOUCH_GPIO = 17                  # TTP223 I/O     -> physical pin 11
MQ2_DO_GPIO = 27                 # MQ-2 DO (via voltage divider!) -> physical pin 13
MQ2_DO_ACTIVE_LOW = True         # most MQ-2 modules pull DO LOW when gas is detected

# ------------------------------------------------------ optional I2C sensors
ADS1115_ENABLED = True           # reads MQ-2 AO for a real air-quality value (optional)
ADS1115_ADDR = 0x48
I2C_BUS = 1
MQ2_DIVIDER_RATIO = 1.5          # AO goes through a 10k/20k divider -> real V = measured x 1.5
BMP280_ENABLED = True            # real air-pressure sensor (optional)
BMP280_ADDRS = (0x76, 0x77)

# -------------------------------------------------------- air-quality tuning
MQ2_WARMUP_S = 60                # ignore the MQ-2 for the first N seconds after power-on
MQ2_CLEAN_V = 0.60               # default clean-air voltage (run tools/calibrate_mq2.py)
AQ_RATIOS = (1.6, 2.5, 4.0)      # ratio vs clean air -> Good / Moderate / Poor / Hazardous
GAS_CONFIRM_READS = 3            # consecutive digital hits before raising the alarm

# ---------------------------------------------------------- comfort / moods
HOT_C = 32.0
COLD_C = 17.0
SLEEPY_AFTER_S = 240             # sleepy eyes after N seconds with no interaction
SLEEP_AFTER_S = 600              # falls asleep (touch or "Buddy" wakes it)

# ----------------------------------------------------------------- screens
ANALYSIS_SECONDS = 10
FPS = 30
FULLSCREEN = True
WINDOW_SIZE = (1024, 600)        # only used when FULLSCREEN = False
SHOW_STATUS_BAR = True

# -------------------------------------------------------------------- audio
MIC_DEVICE = None                # None = automatic (USB mic preferred)
MIC_NAME_HINT = "usb"
AUDIO_PRIORITY = ("bluetooth", "usb", "default")
BT_SPEAKER_MAC = ""              # filled by scripts/pair_bluetooth.sh
BT_RETRY_S = 20
DEFAULT_VOLUME = 85              # percent
VOSK_MODEL_DIR = os.path.join(BASE_DIR, "models", "vosk-model-small-en-in-0.4")
ESPEAK_VOICE = "en-us+f3"        # offline voice
ESPEAK_SPEED = 150
ESPEAK_PITCH = 65
ONLINE_VOICE = True              # nicer Google voice when internet is available
GTTS_LANG = "en"
GTTS_TLD = "co.in"               # Indian-English accent
SPEAK_ANALYSIS = True            # read the numbers out loud in analysis mode
TOUCH_SPEAKS = True
TOUCHSCREEN_ENABLED = True       # the 7-inch HDMI touch display also counts as touch

# --------------------------------------------------------- online "smart" brain
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = "claude-haiku-5-5"
LLM_TIMEOUT_S = 8
OWNER_NAME = "friend"

# ------------------------------------------------- camera + face recognition
CAMERA_ENABLED = True
CAMERA_INDEX = None              # None = try /dev/video0..3 automatically
CAMERA_SIZE = (640, 480)
FACE_INTERVAL_S = 0.6            # how often Luna looks for faces
FACE_MODEL_DIR = os.path.join(BASE_DIR, "models", "face")
FACE_MATCH_THRESHOLD = 0.40      # cosine similarity (higher = stricter). SFace default is 0.363
FACE_ENROLL_SAMPLES = 5
AWAY_S = 45                      # person must be out of view this long before being greeted again
GREET_COOLDOWN_S = 1800
WAKE_ON_FACE = True              # a recognised person walking up wakes a sleeping Luna
ASK_UNKNOWN = True               # "I do not think we have met. What is your name?"
UNKNOWN_ASK_COOLDOWN_S = 900
PERSON_STICKY_S = 6              # keep treating someone as present for N seconds after they leave view

# Who may do what.  Number = lowest rank allowed:
# 0 master | 1 priority (high) | 2 priority (normal) | 3 least priority | 4 anyone / unknown
# Until the first master is enrolled (or if no camera), Luna does not restrict anything.
PERMISSIONS = {
    "system": 0,           # switch to Raspberry Pi OS / calibration
    "manage_people": 0,    # promote, demote, rename, forget people
    "hidden_gallery": 1,   # open / change the PIN-locked hidden gallery
    "settings": 1,         # open the Settings screens (privacy / wifi / bluetooth / display / security)
    "apps": 3,             # music, movies, drawing, room analysis
    "gallery": 2,          # open gallery, show pictures
    "photo": 3,            # take pictures / selfies
    "control": 3,          # volume, timers, sleep / wake
    "introduce": 4,        # introduce someone (they become 'least priority')
    "chat": 4,             # questions, sensors, jokes, room analysis
    "switches": 3,         # turn the ESP32 servo switches on / off
    "calendar": 3,         # open / edit the calendar
    "control_center": 1,   # open the Control Center app (add / remove ESP32 nodes)
}

# ----------------------------------------------------------- photos / gallery
GALLERY_DIR = os.path.join(DATA_DIR, "gallery")
HIDDEN_DIR = os.path.join(DATA_DIR, "hidden")
PIN_FILE = os.path.join(DATA_DIR, "hidden_pin.json")
UI_STATE_FILE = os.path.join(DATA_DIR, "ui_state.json")
PHOTO_COUNTDOWN_S = 3
GROUP_COUNTDOWN_S = 5
IMAGE_VIEW_SECONDS = 10          # "show the image" (timer pauses while you touch the screen)
GALLERY_IDLE_S = 180             # gallery closes by itself after this much inactivity
HIDDEN_IDLE_S = 90               # hidden gallery re-locks sooner

# ------------------------------------------------------------- apps / media
MUSIC_DIR = os.path.join(DATA_DIR, "music")
MOVIES_DIR = os.path.join(DATA_DIR, "movies")
DRAWINGS_DIR = os.path.join(DATA_DIR, "drawings")
SECURITY_DIR = os.path.join(DATA_DIR, "security")
THUMB_DIR = os.path.join(DATA_DIR, "thumbs")
MPV = "mpv"                      # sudo apt install mpv  (plays music + videos)
# Album folders created on first run -> words you can say ("Luna, play a devotional song")
MUSIC_ALIASES = {
    "God":         ["god", "devotional", "spiritual", "bhakti", "bhajan", "religious", "prayer", "worship"],
    "Romantic":    ["romantic", "love", "romance"],
    "Upbeat":      ["upbeat", "party", "dance", "dj", "fast"],
    "Sad":         ["sad", "melancholic", "melancholy", "heartbreak", "emotional"],
    "Chill":       ["chill", "relaxing", "relax", "ambient", "calm", "peaceful"],
    "Motivational": ["motivational", "motivation", "workout", "gym", "energy"],
    "Nostalgic":   ["nostalgic", "retro", "old", "classic", "oldies"],
}
SEEK_SECONDS = 10

# ------------------------------------------------------- USB drives / documents
PDF_DIR = os.path.join(DATA_DIR, "pdfs")          # put PDFs here (or open them straight from a USB drive)
USB_ROOTS = ["/media/*/*", "/media/*", "/run/media/*/*", "/mnt/*"]   # where the desktop mounts pen drives
USB_REQUIRE_MOUNT = True
PDF_BASE_DPI_MAX = 130
PDF_READ_CHARS = 320             # size of each spoken chunk when reading a PDF aloud

# ------------------------------------------------- privacy / people limits
PRIVACY_PIN_FILE = os.path.join(DATA_DIR, "privacy_pin.json")
PRIVACY_PIN_INITIAL = "0223"     # only used ONCE to create the hashed PIN file; change it in Settings > Privacy
MASTER_MAX_PEOPLE, MASTER_PHOTOS = 6, 10
PRIORITY_MAX_PEOPLE, PRIORITY_MAX_PHOTOS = 10, 5
LEAST_SAMPLES = 3                # photos taken when someone is introduced by voice (third priority)

# ------------------------------------------------------------------ security
TELEGRAM_FILE = os.path.join(DATA_DIR, "telegram.json")
SECURITY_COOLDOWN_S = 60         # same person is photographed at most once per minute
INTRUDER_GRACE_S = 15            # unknown face: Luna asks the name, siren starts after this
INTRUDER_GONE_S = 15             # siren stops when the unknown face has left for this long

# ------------------------------------------------------ pressure fallback
LATITUDE = 12.97                 # used only to fetch air pressure online when
LONGITUDE = 77.59                # no BMP280 is fitted. Change to your location.
PRESSURE_REFRESH_S = 900


# =====================================================================
# v2 additions: vault, USB, calendar, ESP32 control center, Telegram bot
# =====================================================================
# ---- hidden vault
VAULT_STATE_FILE = os.path.join(DATA_DIR, "vault_state.json")   # failed-try counter + lockout (survives restarts)
VAULT_MAX_TRIES = 3              # wrong tries before the first lockout
VAULT_LOCK_BASE_S = 30           # first lockout 30 s, doubles every time

# ---- USB pen drive
USB_POLL_S = 2.0                 # how often Luna looks for new drives
MPV_HWDEC = "auto"               # mpv hardware decoding (try "v4l2m2m-copy" if video stutters)
MPV_EXTRA = []                   # extra mpv flags, e.g. ["--vo=gpu"]
TEXT_EXTS = (".txt", ".md")

# ---- calendar
CALENDAR_FILE = os.path.join(DATA_DIR, "calendar.json")
CALENDAR_STATE_FILE = os.path.join(DATA_DIR, "calendar_state.json")
CALENDAR_REMIND_HOUR = 9         # day-prior reminder time (24 h clock)
CALENDAR_REMIND_MINUTE = 0
CALENDAR_CATCHUP_UNTIL_HOUR = 21 # if Luna was off at 09:00, still remind until this hour

# ---- ESP32 control center
ESP32_FILE = os.path.join(DATA_DIR, "esp32.json")
ESP32_MDNS_NAME = "esp32-switch.local"
ESP32_API_KEY = ""               # same value as API_KEY in the ESP32 firmware (leave "" to disable)
ESP32_TIMEOUT_S = 4
ESP32_POLL_S = 15
ESP32_DEFAULT_ANGLE = 45         # flick distance from neutral, degrees
ESP32_LOG_FILE = os.path.join(DATA_DIR, "switch_log.jsonl")

# ---- Telegram bot (token + chat id are set in Settings > Security > Telegram alerts)
TELEGRAM_BOT_ENABLED = True
TELEGRAM_POLL_TIMEOUT_S = 25
TELEGRAM_MAX_FILE_MB = 20        # Bot API download limit
GAS_ALERT_REPEAT_S = 300         # repeat the gas alert every 5 minutes while it lasts

try:
    from config_local import *   # noqa: F401,F403
except ImportError:
    pass

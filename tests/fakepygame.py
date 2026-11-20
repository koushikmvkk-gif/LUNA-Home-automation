"""Minimal stand-in for pygame so the UI code can be import-checked and drawn headlessly (tests only)."""
import sys, types


class Rect:
    def __init__(self, x=0, y=0, w=0, h=0):
        if hasattr(x, "left"):
            x, y, w, h = x.left, x.top, x.width, x.height
        self.left, self.top, self.width, self.height = int(x), int(y), int(w), int(h)
    right = property(lambda s: s.left + s.width)
    bottom = property(lambda s: s.top + s.height)
    centerx = property(lambda s: s.left + s.width // 2)
    centery = property(lambda s: s.top + s.height // 2)
    center = property(lambda s: (s.centerx, s.centery))
    def inflate(self, dx, dy): return Rect(self.left - dx // 2, self.top - dy // 2, self.width + dx, self.height + dy)
    def collidepoint(self, p): return self.left <= p[0] < self.right and self.top <= p[1] < self.bottom


class Surf:
    def __init__(self, size=(10, 10)): self.size = size
    def get_width(self): return self.size[0]
    def get_height(self): return self.size[1]
    def get_size(self): return self.size
    def blit(self, *a, **k): pass
    def fill(self, *a, **k): pass
    def set_alpha(self, *a): pass
    def convert_alpha(self): return self
    def convert(self): return self
    def copy(self): return self
    def subsurface(self, *a): return self


class Font:
    def __init__(self, size): self.size = size
    def render(self, text, aa, col, *a): return Surf((int(len(text) * self.size * 0.5), int(self.size * 1.2)))
    def size_of(self, t): return (int(len(t) * self.size * 0.5), int(self.size))


def install():
    m = types.ModuleType("pygame")
    m.Rect, m.Surface = Rect, lambda *a, **k: Surf(a[0] if a else (10, 10))
    m.SRCALPHA = 1
    m.font = types.SimpleNamespace(SysFont=lambda n, s, bold=False: Font(s), init=lambda: None)
    noop = lambda *a, **k: Rect(0, 0, 1, 1)
    m.draw = types.SimpleNamespace(rect=noop, circle=noop, line=noop, lines=noop, polygon=noop, ellipse=noop, arc=noop)
    m.transform = types.SimpleNamespace(smoothscale=lambda s, size: Surf(size), scale=lambda s, size: Surf(size), rotate=lambda s, a: s, flip=lambda s, *a: s)
    m.image = types.SimpleNamespace(load=lambda p: Surf((100, 80)), save=lambda *a: None)
    m.mouse = types.SimpleNamespace(set_visible=lambda v: None)
    m.QUIT = 256; m.KEYDOWN = 768; m.KEYUP = 769; m.MOUSEBUTTONDOWN = 1025; m.MOUSEBUTTONUP = 1026; m.MOUSEMOTION = 1024
    m.K_ESCAPE = 27; m.K_SPACE = 32; m.K_a = 97; m.K_g = 103
    sys.modules["pygame"] = m
    return m

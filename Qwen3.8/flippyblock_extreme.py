#!/usr/bin/env python3
"""
FLIPPYBLOCK EXTREME
===================
A complete Flappy-Bird-style arcade game in a single file.

  * 100% procedural - every sprite, background, UI skin and every sound
    (SFX + looping chiptune) is synthesized in code at startup.
  * Only dependency: pygame >= 2.
  * Full UI: menu, difficulty select, settings (music/sfx volume,
    fullscreen, fps counter), how-to screen, pause menu, game-over panel
    with medals, persistent best scores, screen shake, particles,
    day/night cycle.

Controls:
    SPACE / UP / W / left mouse   flap
    P or ESC                     pause / resume
    R                            restart (after a fall)
    M                            mute / unmute
    F11                          fullscreen
    ENTER                        confirm buttons

Settings & best scores persist in ~/.flippyblock_extreme.json
"""

import array
import json
import math
import os
import random
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
try:
    import pygame
except ImportError:
    sys.exit("FlippyBlock EXTREME needs pygame (python 3, pygame >= 2).\n"
             "Install it with:  pip install pygame")

# --------------------------------------------------------------------------- #
#  Tuning
# --------------------------------------------------------------------------- #
LOGICAL_W, LOGICAL_H = 400, 700
GROUND_H = 90
GROUND_TOP = LOGICAL_H - GROUND_H
FPS = 60

GRAVITY = 1500.0
FLAP_VY = -400.0
MAX_FALL = 720.0
BIRD_X = 110.0
BIRD_HIT_R = 13.0          # circular hitbox radius (forgiving, classic feel)

PIPE_W = 78
PIPE_CAP_H = 26
PIPE_LIP = 5

DIFFICULTIES = {
    "NORMAL":  dict(speed=155.0, max_speed=240.0, speed_ramp=1.6,
                    gap=178.0, min_gap=150.0, gap_ramp=0.55, spacing=236.0,
                    jump=150.0, body=(94, 200, 110), dark=(38, 105, 52),
                    light=(168, 236, 150)),
    "HARD":    dict(speed=175.0, max_speed=275.0, speed_ramp=2.0,
                    gap=160.0, min_gap=132.0, gap_ramp=0.70, spacing=216.0,
                    jump=170.0, body=(240, 164, 60), dark=(120, 70, 20),
                    light=(255, 214, 120)),
    "EXTREME": dict(speed=195.0, max_speed=320.0, speed_ramp=2.6,
                    gap=146.0, min_gap=118.0, gap_ramp=0.85, spacing=198.0,
                    jump=190.0, body=(226, 82, 92), dark=(104, 28, 44),
                    light=(255, 150, 150)),
}
DIFF_ORDER = ("NORMAL", "HARD", "EXTREME")
MEDALS = ((40, "PLATINUM", (186, 224, 235)),
          (30, "GOLD",       (255, 202, 40)),
          (20, "SILVER",     (205, 210, 216)),
          (10, "BRONZE",     (190, 120, 58)))

SAVE_NAME = ".flippyblock_extreme.json"


# --------------------------------------------------------------------------- #
#  Small helpers
# --------------------------------------------------------------------------- #
def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return a + (b - a) * t


def mixc(a, b, t):
    return (int(lerp(a[0], b[0], t)), int(lerp(a[1], b[1], t)), int(lerp(a[2], b[2], t)))


def _circle_rect(cx, cy, r, rect):
    """Accurate circle vs axis-aligned-rect test."""
    nx = clamp(cx, rect.left, rect.right)
    ny = clamp(cy, rect.top, rect.bottom)
    dx, dy = cx - nx, cy - ny
    return dx * dx + dy * dy <= r * r


_FONT_CACHE = {}


def _font(size):
    fnt = _FONT_CACHE.get(size)
    if fnt is None:
        fnt = pygame.font.Font(None, size)   # pygame's bundled font - no asset file
        _FONT_CACHE[size] = fnt
    return fnt


def text(size, msg, color, shadow=(28, 28, 34)):
    """Render text with an offset drop shadow (cached font, no assets)."""
    fnt = _font(size)
    if shadow is None:
        return fnt.render(msg, True, color)
    main = fnt.render(msg, True, color)
    sh = fnt.render(msg, True, shadow)
    out = pygame.Surface((main.get_width() + 2, main.get_height() + 2), pygame.SRCALPHA)
    out.blit(sh, (2, 2))
    out.blit(main, (0, 0))
    return out


# --------------------------------------------------------------------------- #
#  Procedural audio (all samples generated from math - no audio files)
# --------------------------------------------------------------------------- #
class Audio:
    def __init__(self):
        self.mixer_ok = pygame.mixer.get_init() is not None
        self.sounds = {}
        self.music = None
        self.music_playing = False
        self.vol_music = 3     # steps 0..4 (0 = off)
        self.vol_sfx = 4
        if not self.mixer_ok:
            return
        sr, _fmt, ch = pygame.mixer.get_init()
        self.sounds["flap"] = self._snd(self._flap(sr))
        self.sounds["point"] = self._snd(self._point(sr))
        self.sounds["hit"] = self._snd(self._hit(sr))
        self.sounds["die"] = self._snd(self._die(sr))
        self.sounds["click"] = self._snd(self._click(sr))
        self.sounds["fanfare"] = self._snd(self._fanfare(sr))
        self.music = self._snd(self._music(sr))

    # -- helpers ------------------------------------------------------------
    def _snd(self, samples):
        if not self.mixer_ok:
            return None
        ch = pygame.mixer.get_init()[2]
        data = []
        for s in samples:
            v = int(round(clamp(s, -1.0, 1.0) * 32767))
            data.append(v)
            if ch > 1:
                data.append(v)
        try:
            return pygame.mixer.Sound(buffer=array.array("h", data).tobytes())
        except pygame.error:
            return None

    # -- one-shot sfx ---------------------------------------------------------
    def _flap(self, sr):
        dur, n = 0.085, int(sr * 0.085)
        out = []
        for i in range(n):
            t = i / sr
            ph = 620.0 * t + (900.0 / dur) * 0.5 * t * t          # rising chirp
            s = (0.62 if (ph % 1.0) < 0.5 else -0.22) + 0.25 * math.sin(2 * math.pi * ph)
            env = min(1.0, t / 0.004) * math.exp(-t * 24.0)
            out.append(s * env * 0.55)
        return out

    def _point(self, sr):
        n = int(sr * 0.15)
        out = []
        for i in range(n):
            t = i / sr
            tt, f = (t, 1046.5) if t < 0.07 else (t - 0.07, 1568.0)
            s = math.sin(2 * math.pi * f * tt) + 0.35 * math.sin(4 * math.pi * f * tt)
            env = min(1.0, tt / 0.003) * math.exp(-tt * 14.0)
            out.append(s * env * 0.45)
        return out

    def _hit(self, sr):
        n = int(sr * 0.15)
        out, lp = [], 0.0
        for i in range(n):
            t = i / sr
            v = random.uniform(-1.0, 1.0)
            lp += (v - lp) * 0.35
            s = lp * 0.9 + math.sin(2 * math.pi * 70.0 * t) * 0.8 * math.exp(-t * 10.0)
            out.append(s * math.exp(-t * 16.0) * 0.8)
        return out

    def _die(self, sr):
        dur, n = 0.42, int(sr * 0.42)
        out, lp = [], 0.0
        for i in range(n):
            t = i / sr
            k = t / dur
            lp += (random.uniform(-1.0, 1.0) - lp) * (0.85 - 0.5 * k)
            env = math.sin(math.pi * min(1.0, k)) ** 1.4
            out.append(lp * env * 0.5)
        return out

    def _click(self, sr):
        n = int(sr * 0.05)
        return [math.sin(2 * math.pi * 1150.0 * (i / sr)) * math.exp(-(i / sr) * 70.0) * 0.5
                for i in range(n)]

    def _fanfare(self, sr):
        notes = (659.25, 880.0, 1174.66)
        len_seg = 0.09
        n = int(sr * len_seg * 3)
        out = []
        for i in range(n):
            t = i / sr
            seg = min(2, int(t / len_seg))
            tt = t - seg * len_seg
            f = notes[seg]
            tri = 2.0 * abs(2.0 * ((f * tt) % 1.0) - 1.0) - 1.0
            env = min(1.0, tt / 0.004) * math.exp(-tt * 16.0)
            out.append((tri * 0.7 + math.sin(2 * math.pi * f * tt) * 0.5) * env * 0.38)
        return out

    # -- looping 4-second chiptune ------------------------------------------
    def _music(self, sr):
        eighth = 0.25                                             # 120 bpm
        mel = [523.25, 659.25, 784.0, 659.25,
               587.33, 659.25, 523.25, 587.33,
               440.0, 523.25, 659.25, 523.25,
               493.88, 587.33, 784.0, 587.33]
        bass = [130.81, 110.0, 130.81, 110.0, 174.61, 164.81, 98.0, 130.81]
        n = int(sr * eighth * 16)
        smp = [0.0] * n
        d = 0.02
        for k, f in enumerate(mel):
            i0 = int(sr * (d + eighth * k))
            for j in range(int(sr * eighth)):
                i = i0 + j
                if i >= n:
                    break
                t = j / sr
                s = math.sin(2 * math.pi * f * t) * 0.6 + math.sin(4 * math.pi * f * t) * 0.18
                smp[i] += s * min(1.0, t / 0.003) * math.exp(-t * 7.0) * 0.30
        for k, f in enumerate(bass):
            i0 = int(sr * (d + 2 * eighth * k))
            for j in range(int(sr * 2 * eighth)):
                i = i0 + j
                if i >= n:
                    break
                t = j / sr
                s = math.sin(2 * math.pi * f * t) * 0.8 + math.sin(4 * math.pi * f * t) * 0.25
                smp[i] += s * min(1.0, t / 0.004) * math.exp(-t * 4.5) * 0.22
        for k in range(8):                                        # kick
            i0 = int(sr * (d + 2 * eighth * k))
            ph = 0.0
            for j in range(int(sr * 0.11)):
                i = i0 + j
                if i >= n:
                    break
                t = j / sr
                ph += 110.0 * (0.30 ** (t / 0.11)) / sr
                smp[i] += math.sin(2 * math.pi * ph) * math.exp(-t * 22.0) * 0.45
        for k in range(16):                                       # hats
            i0 = int(sr * (d + eighth * k + (0.12 if k % 2 else 0.0)))
            for j in range(int(sr * 0.035)):
                i = i0 + j
                if i >= n:
                    break
                t = j / sr
                smp[i] += random.uniform(-1.0, 1.0) * math.exp(-t * 90.0) * (0.06 if k % 2 else 0.03)
        peak = max(1e-6, max(abs(s) for s in smp))
        g = 0.85 / peak
        fi = int(sr * 0.012)
        fo = int(sr * 0.03)
        for i in range(n):
            s = smp[i] * g
            if i < fi:
                s *= i / fi
            if i >= n - fo:
                s *= max(0.0, (n - 1 - i)) / fo
            smp[i] = s
        return smp

    # -- runtime --------------------------------------------------------------
    def sfx(self, name):
        if not self.mixer_ok or self.vol_sfx <= 0:
            return
        snd = self.sound(name)
        if snd is not None:
            try:
                snd.set_volume(float(self.vol_sfx) / 4.0)
                snd.play()
            except pygame.error:
                pass

    def sound(self, name):
        return self.sounds.get(name)

    def music_on(self):
        if self.mixer_ok and self.music is not None and self.vol_music > 0 and not self.music_playing:
            try:
                self.music.set_volume(float(self.vol_music) / 4.0)
                self.music.play(-1)
                self.music_playing = True
            except pygame.error:
                pass

    def music_off(self):
        if self.music_playing and self.music is not None:
            try:
                self.music.stop()
            except pygame.error:
                pass
            self.music_playing = False


# --------------------------------------------------------------------------- #
#  Simple entities
# --------------------------------------------------------------------------- #
class Bird:
    __slots__ = ("x", "y", "vy", "rot", "t", "dead")

    def __init__(self):
        self.x = BIRD_X
        self.y = 300.0
        self.vy = 0.0
        self.rot = -18.0
        self.t = 0.0
        self.dead = False

    @property
    def wing(self):
        return ("up", "mid", "down", "mid")[int(self.t * 11) % 4]


class Pipe:
    __slots__ = ("x", "top", "gap", "scored")

    def __init__(self, x, top, gap):
        self.x = float(x)
        self.top = int(top)
        self.gap = int(gap)
        self.scored = False

    @property
    def bottom(self):
        return self.top + self.gap


class Button:
    def __init__(self, x, y, w, h, label, action, size=24,
                 fill=(255, 209, 68), hover=(255, 222, 108),
                 text_color=None):
        self.rect = pygame.Rect(x, y, w, h)
        self.action = action
        self.label = label
        self.size = size
        self.fill = fill
        self.hover_fill = hover
        self.text_color = text_color if text_color is not None else (48, 38, 16)
        self.hover = False
        self.rebuild()

    def rebuild(self):
        self.sn = self._surface(self.fill)
        self.sv = self._surface(self.hover_fill)

    def _surface(self, fill):
        s = pygame.Surface((self.rect.w, self.rect.h), pygame.SRCALPHA)
        pygame.draw.rect(s, (30, 30, 36), (1, 2, self.rect.w - 2, self.rect.h - 2), border_radius=10)
        pygame.draw.rect(s, fill, (3, 3, self.rect.w - 6, self.rect.h - 6), border_radius=8)
        if self.label:
            t = text(self.size, self.label, self.text_color, None)
            s.blit(t, (self.rect.w // 2 - t.get_width() // 2,
                       self.rect.h // 2 - t.get_height() // 2 + 1))
        return s

    def refresh_label(self, label, fill, hover_fill):
        self.label = label
        self.fill = fill
        self.hover_fill = hover_fill
        self.rebuild()

    def update(self, pos):
        self.hover = self.rect.collidepoint(pos)

    def draw(self, surf):
        surf.blit(self.sv if self.hover else self.sn, self.rect.topleft)


# --------------------------------------------------------------------------- #
#  The game
# --------------------------------------------------------------------------- #
class Game:
    def __init__(self):
        self.running = True
        self.window = pygame.display.get_surface()
        self.screen = pygame.Surface((LOGICAL_W, LOGICAL_H))
        self.world = pygame.Surface((LOGICAL_W, LOGICAL_H))

        self.audio = Audio()
        saved = self._load_save()
        self.best = {d: int(saved.get("best", {}).get(d, 0)) for d in DIFF_ORDER}
        self.difficulty = saved.get("difficulty", "EXTREME")
        if self.difficulty not in DIFFICULTIES:
            self.difficulty = "EXTREME"
        self.show_fps = bool(saved.get("show_fps", False))
        self.audio.vol_music = int(clamp(saved.get("music", 3), 0, 4))
        self.audio.vol_sfx = int(clamp(saved.get("sfx", 4), 0, 4))
        self.last_sfx = self.audio.vol_sfx or 4

        # --- procedural art ------------------------------------------------
        self.frames = self._make_bird_frames()
        self.medals = {name: self._make_medal(col) for (_t, name, col) in MEDALS}
        self.medals_small = {n: pygame.transform.scale(m, (44, 44))
                             for n, m in self.medals.items()}
        self.sky_day = self._make_sky((111, 197, 232), (189, 231, 240), night=False)
        self.sky_night = self._make_sky((9, 14, 36), (44, 58, 92), night=True)
        self.ground = self._make_ground()
        self.pipe_skins = {d: self._make_pipe_skins(cfg) for d, cfg in DIFFICULTIES.items()}
        rd = random.Random()
        self.cloud_shapes = [self._make_cloud(random.Random(a)) for a in (1, 2, 3)]
        self.clouds = []
        for i in range(7):
            s = self.cloud_shapes[i % 3]
            self.clouds.append(dict(x=rd.uniform(-200, LOGICAL_W + 240.0),
                                    y=rd.uniform(26, GROUND_TOP - 190.0),
                                    spd=10.0 + 16.0 * (0.6 + i / 6.0),
                                    surf=s))

        # --- cached static text/ui -----------------------------------------
        letters = []
        for ch in "FLIPPYBLOCK":
            letters.append(text(46, ch, (255, 255, 255), (35, 38, 48)))
        self.title_letters = letters
        self.title_width = sum(l.get_width() for l in letters)
        self.s_extreme = text(30, "EXTREME", (255, 198, 50), (140, 40, 25))
        self.s_getready = text(44, "GET READY!", (250, 250, 250), (40, 40, 50))
        self.s_hint = text(24, "SPACE / CLICK TO FLAP", (250, 250, 250), (40, 40, 50))
        self.s_newbest = text(22, "NEW BEST!", (255, 92, 72), (255, 255, 255))
        self.s_paused = text(46, "PAUSED", (255, 255, 255), (40, 40, 50))
        self.s_paused_hint = text(22, "P / ESC  resume", (200, 205, 215), (30, 30, 40))
        self.s_settings = text(36, "SETTINGS", (255, 250, 235), (120, 84, 30))
        self.s_howto = text(36, "HOW TO PLAY", (255, 250, 235), (120, 84, 30))
        self.s_gameoverhead = text(40, "GAME OVER", (232, 96, 38), (90, 45, 15))
        self.s_footer1 = text(18, "FLIPPYBLOCK EXTREME v1.0", (60, 66, 80), (255, 255, 255))
        self.s_footer2 = text(18, "100% procedural art & audio  -  only dependency: pygame",
                              (60, 66, 80), (255, 255, 255))
        self.digits = [text(52, str(i), (255, 255, 255), (30, 30, 38)) for i in range(10)]
        self.s_plus = text(22, "+1", (255, 245, 160), (70, 50, 10))
        self.help_lines = [
            text(22, "FLAP      SPACE / W / UP / LEFT CLICK", (66, 54, 40), (255, 255, 255)),
            text(22, "PAUSE     P  or  ESC", (66, 54, 40), (255, 255, 255)),
            text(22, "RESTART   R  (after a fall)", (66, 54, 40), (255, 255, 255)),
            text(22, "MUTE      M      FULLSCREEN    F11", (66, 54, 40), (255, 255, 255)),
            text(22, "ENTER     confirms menu buttons", (66, 54, 40), (255, 255, 255)),
            text(22, "Score 1 per pipe. Pipes speed up and the", (100, 86, 60), (255, 255, 255)),
            text(22, "gap tightens as you score. Night falls at 35!", (100, 86, 60), (255, 255, 255)),
            text(20, "Medals", (100, 86, 60), (255, 255, 255)),
        ]
        self.help_medal_nums = [text(18, "10", (100, 86, 60), (255, 255, 255)),
                                text(18, "20", (100, 86, 60), (255, 255, 255)),
                                text(18, "30", (100, 86, 60), (255, 255, 255)),
                                text(18, "40", (100, 86, 60), (255, 255, 255))]
        self.help_credits = text(16, "v1.0  -  every sprite & sound synthesized in code",
                                 (150, 135, 105), (255, 255, 255))

        # --- run state -------------------------------------------------------
        self.bird = Bird()
        self.pipes = []
        self.particles = []
        self.popups = []
        self.score = 0
        self.start_best = 0
        self.exceeded_best = False
        self.new_best = False
        self.medal = None
        self.panel_y = -220.0
        self.landed = False
        self.world_x = 0.0
        self.night_blend = 0.0
        self.night_target = 0.0
        self.flash = 0.0
        self.shake_t = 0.0
        self.shake_dur = 0.0
        self.shake_mag = 0.0
        self.sched = []          # (time, sfx name)
        self.time = 0.0
        self.menu_t = 0.0
        self.buttons = []
        self.diff_light = DIFFICULTIES[self.difficulty]["light"]
        self._refresh_best()
        self.s_mode = text(20, self.difficulty, self.diff_light, (35, 35, 40))

        self._fit_window()
        self.show_menu()
        self.audio.music_on()

    # ------------------------------------------------------------------ #
    #  Persistence
    # ------------------------------------------------------------------ #
    def _save_path(self):
        return os.path.join(os.path.expanduser("~"), SAVE_NAME)

    def _load_save(self):
        try:
            with open(self._save_path()) as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self):
        data = {"best": self.best, "music": self.audio.vol_music, "sfx": self.audio.vol_sfx,
                "difficulty": self.difficulty, "show_fps": self.show_fps}
        try:
            tmp = self._save_path() + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(data, fh)
            os.replace(tmp, self._save_path())
        except OSError:
            pass   # read-only home dir etc. - play on without saving

    # ------------------------------------------------------------------ #
    #  Procedural sprite builders
    # ------------------------------------------------------------------ #
    def _make_bird_frames(self):
        S = 34
        OUTLINE = (52, 40, 22)
        body = pygame.Surface((S, S), pygame.SRCALPHA)
        pygame.draw.rect(body, (255, 201, 64), (2, 2, 29, 29), border_radius=9)
        body.set_clip(pygame.Rect(3, 3, 27, 27))
        pygame.draw.rect(body, (233, 158, 40), (3, 19, 27, 10), border_radius=6)
        pygame.draw.rect(body, (255, 229, 138), (4, 3, 12, 9), border_radius=5)
        pygame.draw.ellipse(body, (222, 222, 222), (10, 16, 19, 12))
        pygame.draw.ellipse(body, (255, 255, 255), (11, 17, 17, 10))
        body.set_clip(None)
        pygame.draw.circle(body, OUTLINE, (22, 11), 8, 2)
        pygame.draw.circle(body, (255, 255, 255), (22, 11), 6)
        pygame.draw.circle(body, (40, 40, 40), (24, 12), 3)
        pygame.draw.rect(body, OUTLINE, (2, 2, 29, 29), width=2, border_radius=9)

        wing = pygame.Surface((17, 12), pygame.SRCALPHA)
        pygame.draw.rect(wing, (250, 250, 250), (1, 1, 15, 10), border_radius=5)
        pygame.draw.rect(wing, OUTLINE, (1, 1, 15, 10), width=2, border_radius=5)

        frames = {}
        for name, rot, yoff in (("up", 38, -5), ("mid", 0, 0), ("down", -38, 6)):
            f = body.copy()
            w = pygame.transform.rotate(wing, -rot)
            f.blit(w, (7 - w.get_width() // 2, 14 - w.get_height() // 2 + yoff))
            frames[name] = f
        dead = body.copy()
        for x0, y0 in ((16, 6), (26, 6)):
            pygame.draw.line(dead, OUTLINE, (x0, y0), (x0 + 9, y0 + 9), 3)
            pygame.draw.line(dead, OUTLINE, (x0 + 9, y0), (x0, y0 + 9), 3)
        frames["dead"] = dead
        return frames

    def _make_pipe_skins(self, cfg):
        body, dark, light = cfg["body"], cfg["dark"], cfg["light"]
        OUTH = (24, 30, 24)

        def column(x, w):
            if x < 3 or x >= w - 3:
                return dark
            if x < 7:
                return mixc(dark, body, (x - 3) / 4.0)
            if 8 <= x <= 18:
                return light
            if x >= w - 13:
                return mixc(body, dark, (x - (w - 13)) / 10.0)
            return body

        strip = pygame.Surface((PIPE_W, 1))
        for x in range(PIPE_W):
            pygame.draw.rect(strip, column(x, PIPE_W), (x, 0, 1, 1))

        cap_w = PIPE_W + 2 * PIPE_LIP
        cap = pygame.Surface((cap_w, PIPE_CAP_H), pygame.SRCALPHA)
        cs = pygame.Surface((cap_w, 1))
        for x in range(cap_w):
            pygame.draw.rect(cs, column(x, cap_w), (x, 0, 1, 1))
        cap.blit(pygame.transform.scale(cs, (cap_w, PIPE_CAP_H)), (0, 0))
        hi = pygame.Surface((cap_w, PIPE_CAP_H), pygame.SRCALPHA)
        hi.fill((255, 255, 255, 60))
        hi.set_clip(pygame.Rect(2, 1, cap_w - 4, 4))
        cap.blit(hi, (0, 0))
        sh = pygame.Surface((cap_w, PIPE_CAP_H), pygame.SRCALPHA)
        sh.fill((0, 0, 0, 70))
        sh.set_clip(pygame.Rect(2, PIPE_CAP_H - 5, cap_w - 4, 4))
        cap.blit(sh, (0, 0))
        pygame.draw.rect(cap, OUTH, (0, 0, cap_w - 1, PIPE_CAP_H - 1), width=2, border_radius=5)
        return dict(strip=strip, cap=cap)

    def _draw_pipe(self, surf, skins, x, oy_boost):
        st, cap = skins["strip"], skins["cap"]
        if self.state not in ("ready", "playing", "dead", "gameover", "paused"):
            return
        for p in self.pipes:
            if p.x < -100 or p.x > LOGICAL_W + 40:
                continue
            h1 = max(4, p.top - PIPE_CAP_H)
            surf.blit(pygame.transform.scale(st, (PIPE_W, h1)), (x + int(p.x), 0))
            surf.blit(cap, (x + int(p.x) - PIPE_LIP, p.top - PIPE_CAP_H))
            gb = p.bottom
            h2 = max(4, GROUND_TOP - gb - PIPE_CAP_H)
            surf.blit(pygame.transform.scale(st, (PIPE_W, h2)), (x + int(p.x), gb + PIPE_CAP_H))
            surf.blit(cap, (x + int(p.x) - PIPE_LIP, gb))

    def _make_sky(self, top, bottom, night=False):
        s = pygame.Surface((LOGICAL_W, GROUND_TOP), pygame.SRCALPHA)
        rgb = pygame.Surface((LOGICAL_W, GROUND_TOP))
        for y in range(GROUND_TOP):
            t = y / (GROUND_TOP - 1)
            pygame.draw.line(rgb, mixc(top, bottom, t), (0, y), (LOGICAL_W, y))
        s.blit(rgb, (0, 0))
        rd = random.Random(13 if night else 7)
        if not night:
            glow = pygame.Surface((140, 140), pygame.SRCALPHA)
            for r, a in ((60, 26), (48, 46), (36, 76)):
                pygame.draw.circle(glow, (255, 244, 170, a), (70, 70), r)
            pygame.draw.circle(s, (255, 250, 205), (320, 84), 26)
            s.blit(glow, (320 - 70, 84 - 70))
            col = (234, 248, 255)
            for _ in range(9):
                x = rd.randint(-14, LOGICAL_W + 6)
                r = rd.randint(18, 42)
                cy = GROUND_TOP - 24 - rd.randint(0, 26)
                pygame.draw.circle(s, col, (x, cy), r)
            pygame.draw.rect(s, col, (0, GROUND_TOP - 26, LOGICAL_W, 26))
        else:
            for _ in range(70):
                x = rd.randint(0, LOGICAL_W - 1)
                y = rd.randint(4, int(GROUND_TOP * 0.72))
                b = rd.randint(120, 255)
                r = 2 if (b > 225 and rd.random() < 0.4) else 1
                pygame.draw.circle(s, (b, b, min(255, b + 18)), (x, y), r)
            pygame.draw.circle(s, (238, 236, 214), (318, 86), 25)
            for cx, cy, cr in ((310, 78, 5), (326, 92, 4), (314, 95, 3)):
                pygame.draw.circle(s, (214, 210, 186), (cx, cy), cr)
            x = -8
            while x < LOGICAL_W:
                w = rd.randint(26, 52)
                h = rd.randint(30, 110)
                pygame.draw.rect(s, rd.choice(((24, 32, 62), (29, 39, 74), (20, 27, 54))),
                                 (x, GROUND_TOP - h, w, h))
                for wy in range(GROUND_TOP - h + 6, GROUND_TOP - 8, 11):
                    for wx in range(x + 4, x + w - 5, 9):
                        if rd.random() < 0.40:
                            pygame.draw.rect(
                                s,
                                (255, 214, 130) if rd.random() < 0.75 else (158, 202, 255),
                                (wx, wy, 3, 4))
                x += w + rd.randint(2, 9)
        return s

    def _make_ground(self):
        cell = pygame.Surface((24, GROUND_H))
        light, dark = (126, 208, 76), (106, 183, 62)
        for y in range(16):
            for x in range(24):
                cell.set_at((x, y), dark if (x - y) % 24 < 12 else light)
        pygame.draw.rect(cell, (84, 58, 20), (0, 16, 24, 4))
        pygame.draw.rect(cell, (222, 196, 126), (0, 20, 24, GROUND_H - 20))
        rd = random.Random(4)
        for _ in range(10):
            x, y = rd.randint(0, 20), rd.randint(26, GROUND_H - 6)
            pygame.draw.rect(cell, rd.choice(((196, 170, 106), (240, 220, 150), (178, 150, 92))),
                             (x, y, 3, 2))
        W2 = LOGICAL_W + 24
        strip = pygame.Surface((W2, GROUND_H))
        for x in range(0, W2, 24):
            strip.blit(cell, (x, 0))
        return strip

    def _make_cloud(self, rd):
        s = pygame.Surface((150, 60), pygame.SRCALPHA)
        base_y = 36
        count = rd.randint(4, 6)
        for i in range(count):
            r = rd.randint(13, 22)
            x = int(14 + i * ((150 - 28) / max(1, count - 1))) + rd.randint(-5, 5)
            y = base_y + rd.randint(-8, 4)
            pygame.draw.circle(s, (210, 228, 244, 255), (x, y + 5), r)
            pygame.draw.circle(s, (255, 255, 255, 255), (x, y), r - 1)
        return s

    def _make_medal(self, color):
        size = 64
        s = pygame.Surface((size, size), pygame.SRCALPHA)
        ring = tuple(max(0, int(c * 0.55)) for c in color)
        inner = tuple(min(255, int(c * 1.12)) for c in color)
        pygame.draw.circle(s, color, (32, 32), 29)
        pygame.draw.circle(s, ring, (32, 32), 29, 4)
        pygame.draw.circle(s, inner, (32, 32), 20)
        pts_out, pts = [], []
        for i in range(10):
            ang = math.radians(-90 + i * 36)
            r = 14.0 if i % 2 == 0 else 6.0
            pts.append((32 + r * math.cos(ang), 32 + r * math.sin(ang)))
            r2 = 16.0 if i % 2 == 0 else 7.5
            pts_out.append((32 + r2 * math.cos(ang), 32 + r2 * math.sin(ang)))
        pygame.draw.polygon(s, (60, 45, 20), pts_out)
        pygame.draw.polygon(s, (255, 255, 255), pts)
        return s

    # ------------------------------------------------------------------ #
    #  Window / scaling
    # ------------------------------------------------------------------ #
    def _fit_window(self):
        w, h = self.window.get_size()
        self.scale = min(w / LOGICAL_W, h / LOGICAL_H) if w and h else 1.0
        self.w0 = max(1, int(LOGICAL_W * self.scale))
        self.h0 = max(1, int(LOGICAL_H * self.scale))
        self.ox = max(0, (w - self.w0) // 2)
        self.oy = max(0, (h - self.h0) // 2)

    def mouse_logical(self, pos):
        if self.scale <= 0.01:
            return (-999.0, -999.0)
        return ((pos[0] - self.ox) / self.scale, (pos[1] - self.oy) / self.scale)

    def _in_logical(self, lp):
        return 0.0 <= lp[0] <= LOGICAL_W and 0.0 <= lp[1] <= LOGICAL_H

    def toggle_fullscreen(self):
        try:
            is_fs = bool(pygame.display.get_surface().get_flags() & pygame.FULLSCREEN)
            if is_fs:
                pygame.display.set_mode((LOGICAL_W, LOGICAL_H), pygame.RESIZABLE)
            else:
                pygame.display.set_mode((0, 0), pygame.FULLSCREEN | pygame.RESIZABLE)
            self.window = pygame.display.get_surface()
            self._fit_window()
            self.audio.sfx("click")
        except pygame.error:
            pass

    # ------------------------------------------------------------------ #
    #  State transitions
    # ------------------------------------------------------------------ #
    def _set_state(self, s):
        self.state = s
        self.state_t = 0.0
        suffix = f" - {self.score}" if s in ("ready", "playing") else ""
        pygame.display.set_caption("FlippyBlock EXTREME" + suffix)

    def _refresh_best(self):
        self.s_best = text(22, f"BEST {self.best[self.difficulty]}",
                           (40, 44, 52), (255, 255, 255))

    def show_menu(self):
        self._set_state("menu")
        self._build_menu_buttons()
        pygame.mouse.set_visible(True)

    def _build_menu_buttons(self):
        self.buttons = [
            Button(100, 408, 200, 52, "PLAY", self.start_run, size=32,
                   fill=(255, 150, 44), hover=(255, 172, 70)),
            Button(100, 468, 200, 38, f"MODE: {self.difficulty}", self.cycle_difficulty),
            Button(100, 536, 200, 38, "SETTINGS", self.show_settings),
            Button(100, 580, 200, 38, "HOW TO PLAY", self.show_help),
        ]

    def show_settings(self):
        self._set_state("settings")
        self._build_settings()
        pygame.mouse.set_visible(True)

    def _build_settings(self):
        ms, ss = self.audio.vol_music, self.audio.vol_sfx
        self.buttons = []
        for i in range(5):
            on = i <= ms
            self.buttons.append(Button(206 + i * 28, 168, 24, 24, str(i),
                                       lambda v=i: self.set_music(v), size=15,
                                       fill=(126, 214, 120) if on else (84, 88, 99),
                                       hover=(156, 234, 150) if on else (104, 108, 119),
                                       text_color=(24, 40, 24) if on else (225, 228, 235)))
        for i in range(5):
            on = i <= ss
            self.buttons.append(Button(206 + i * 28, 228, 24, 24, str(i),
                                       lambda v=i: self.set_sfx(v), size=15,
                                       fill=(126, 214, 120) if on else (84, 88, 99),
                                       hover=(156, 234, 150) if on else (104, 108, 119),
                                       text_color=(24, 40, 24) if on else (225, 228, 235)))
        is_fs = bool(pygame.display.get_surface().get_flags() & pygame.FULLSCREEN)
        self.buttons.append(Button(90, 272, 220, 40,
                                   f"FULLSCREEN: {'ON' if is_fs else 'OFF'}",
                                   self.toggle_fullscreen))
        self.buttons.append(Button(90, 320, 220, 40,
                                   f"FPS COUNTER: {'ON' if self.show_fps else 'OFF'}",
                                   self.toggle_fps))
        self.buttons.append(Button(150, 372, 100, 40, "BACK", self.show_menu))

    def show_help(self):
        self._set_state("help")
        self.buttons = [Button(140, 462, 120, 44, "BACK", self.show_menu, size=24)]
        pygame.mouse.set_visible(True)

    def set_music(self, v):
        self.audio.vol_music = int(v)
        if self.audio.vol_music > 0:
            self.audio.music_on()
        else:
            self.audio.music_off()
        try:
            if self.audio.music is not None:
                self.audio.music.set_volume(self.audio.vol_music / 4.0)
        except pygame.error:
            pass
        self._save()
        if self.state == "settings":
            self._build_settings()

    def set_sfx(self, v):
        self.audio.vol_sfx = int(v)
        self._save()
        self.audio.sfx("click") if v > 0 else None
        if self.state == "settings":
            self._build_settings()

    def toggle_fps(self):
        self.show_fps = not self.show_fps
        self._save()
        self.audio.sfx("click")
        self._build_settings()

    def cycle_difficulty(self):
        i = DIFF_ORDER.index(self.difficulty)
        self.difficulty = DIFF_ORDER[(i + 1) % len(DIFF_ORDER)]
        self.diff_light = DIFFICULTIES[self.difficulty]["light"]
        self.s_mode = text(20, self.difficulty, self.diff_light, (35, 35, 40))
        self._refresh_best()
        self._save()
        for b in self.buttons:   # refresh label: button #1 is MODE
            if b.label.startswith("MODE"):
                b.refresh_label(f"MODE: {self.difficulty}", (255, 209, 68), (255, 222, 108))
                break

    def toggle_mute(self):
        if self.audio.vol_sfx > 0:
            self.last_sfx = self.audio.vol_sfx
            self.audio.vol_sfx = 0
        else:
            self.audio.vol_sfx = self.last_sfx or 4
        self._save()
        self.audio.sfx("click")
        if self.state == "settings":
            self._build_settings()

    def start_run(self):
        self.pipes = []
        self.score = 0
        self.new_best = False
        self.medal = None
        self.popups = []
        self.particles = []
        self.sched = []
        self.night_blend = 0.0
        self.night_target = 0.0
        self.world_x = 0.0
        self.flash = 0.0
        self.shake_t = 0.0
        self.shake_dur = 0.0
        self.landed = False
        self.exceeded_best = False
        self.start_best = self.best[self.difficulty]
        self.bird.__init__()
        self._refresh_best()
        self.s_mode = text(20, self.difficulty, self.diff_light, (35, 35, 40))
        pygame.display.set_caption("FlippyBlock EXTREME")
        pygame.mouse.set_visible(False)
        self.buttons = []
        self._set_state("ready")

    def do_flap(self):
        if self.state == "ready":
            self._set_state("playing")
            self.add_pipe(LOGICAL_W + 280)      # first pipe arrives with grace time
        if self.state != "playing":
            return
        self.bird.vy = FLAP_VY
        self.bird.t = 0.0
        self.audio.sfx("flap")
        self.spawn_particles(5, (BIRD_X - 14, self.bird.y + 12),
                             ((255, 255, 255), (225, 225, 235)), (25, 80), (2, 4),
                             (0.25, 0.5), -40.0, bias=(-40.0, 10.0))

    def pause(self):
        if self.state not in ("ready", "playing"):
            return
        self.paused_from = self.state
        self.buttons = [
            Button(130, 252, 140, 48, "RESUME", self.resume, size=26,
                   fill=(255, 150, 44), hover=(255, 172, 70)),
            Button(130, 308, 140, 42, "RESTART", self.start_run, size=24),
            Button(130, 358, 140, 42, "MENU", self.show_menu, size=24),
        ]
        self._set_state("paused")
        pygame.mouse.set_visible(True)

    def resume(self):
        if self.state != "paused":
            return
        self._set_state(self.paused_from)
        pygame.mouse.set_visible(False)

    def add_pipe(self, x):
        cfg = DIFFICULTIES[self.difficulty]
        gap = max(cfg["min_gap"], cfg["gap"] - self.score * cfg["gap_ramp"])
        tmin, tmax = 64.0, GROUND_TOP - 64.0 - gap
        if self.pipes:
            pc = (self.pipes[-1].top + self.pipes[-1].bottom) / 2.0
            jump = min(cfg["jump"] + self.score * 1.2, 235.0)
            lo, hi = max(pc - jump, tmin), min(pc + jump, tmax)
        else:
            lo, hi = tmin, tmax
        center = random.uniform(lo, hi)
        top = int(clamp(center - gap / 2.0, tmin, tmax))
        self.pipes.append(Pipe(x, top, int(gap)))

    def _score_pass(self):
        self.score += 1
        self.audio.sfx("point")
        self.popups.append([BIRD_X + 48, self.bird.y - 32, 0.0])
        pygame.display.set_caption(f"FlippyBlock EXTREME - {self.score}")
        if not self.exceeded_best and self.score > self.start_best:
            self.exceeded_best = True
        self.night_target = 1.0 if (self.score // 35) % 2 == 1 else 0.0

    def _handle_hit(self):
        b = self.bird
        b.vy = min(b.vy, 0.0) - 60.0
        b.dead = True
        self.landed = (b.y + BIRD_HIT_R >= GROUND_TOP)
        self.flash = 1.0
        self.shake(9.0, 0.45)
        self.audio.sfx("hit")
        self.sched.append((self.time + 0.14, "die"))
        self.spawn_particles(14, (b.x, b.y),
                             ((255, 214, 80), (255, 244, 190), (255, 255, 255)),
                             (60, 240), (3, 6), (0.35, 0.7), 300.0)
        self._set_state("dead")

    def _finish_death(self):
        self.medal = None
        for t, name, _c in MEDALS:
            if self.score >= t:
                self.medal = name
                break
        if self.score > self.best[self.difficulty]:
            self.best[self.difficulty] = self.score
            self.new_best = True
            self.sched.append((self.time + 0.30, "fanfare"))
            self._save()
        self._refresh_best()
        self.buttons = [
            Button(130, 0, 140, 48, "RESTART", self.start_run, size=26,
                   fill=(255, 150, 44), hover=(255, 172, 70)),
            Button(130, 0, 140, 42, "MENU", self.show_menu, size=24),
        ]
        self._set_state("gameover")
        pygame.mouse.set_visible(True)

    # ------------------------------------------------------------------ #
    #  Particles & shake
    # ------------------------------------------------------------------ #
    def shake(self, mag, dur):
        self.shake_mag, self.shake_dur, self.shake_t = mag, dur, dur

    def _shake_offset(self):
        if self.shake_t <= 0:
            return 0, 0
        m = self.shake_mag * (self.shake_t / max(0.0001, self.shake_dur))
        return int(random.uniform(-m, m)), int(random.uniform(-m, m))

    def spawn_particles(self, n, pos, colors, speed, size, life, g, bias=(0.0, 0.0)):
        for _ in range(n):
            a = random.uniform(0.0, math.tau)
            sp = random.uniform(*speed)
            self.particles.append(dict(
                x=pos[0] + random.uniform(-4, 4), y=pos[1] + random.uniform(-4, 4),
                vx=math.cos(a) * sp + bias[0], vy=math.sin(a) * sp + bias[1],
                age=0.0, life=random.uniform(*life),
                color=random.choice(colors), size=random.randint(*size), g=g))

    # ------------------------------------------------------------------ #
    #  Updates per state
    # ------------------------------------------------------------------ #
    def update_ready(self, dt):
        self.bird.t += dt
        self.bird.y = 300 + math.sin(self.time * 3.0) * 10
        self.bird.vy = 0.0

    def update_playing(self, dt):
        cfg = DIFFICULTIES[self.difficulty]
        spd = min(cfg["max_speed"], cfg["speed"] + self.score * cfg["speed_ramp"])
        self.world_x += spd * dt
        b = self.bird
        b.t += dt * (1.0 if b.vy < 0 else 0.4)
        b.vy = min(b.vy + GRAVITY * dt, MAX_FALL)
        b.y += b.vy * dt
        if b.y < BIRD_HIT_R:                     # ceiling clamp (classic rules: no death)
            b.y = BIRD_HIT_R
            b.vy = max(b.vy, 0.0)
        tgt = -26.0 + clamp((b.vy + 120.0) / (MAX_FALL + 120.0), 0.0, 1.0) * 118.0
        b.rot += (tgt - b.rot) * min(1.0, dt * 14.0)

        for p in self.pipes:
            p.x -= spd * dt
        if self.pipes and self.pipes[0].x < -PIPE_W - 2 * PIPE_LIP - 8:
            self.pipes.pop(0)

        if self.pipes and self.pipes[-1].x <= LOGICAL_W + 50.0 - cfg["spacing"]:
            self.add_pipe(max(LOGICAL_W + 50, int(self.pipes[-1].x + cfg["spacing"])))

        cx, r = b.x, BIRD_HIT_R
        for p in self.pipes:
            if p.x > b.x + 70 or p.x + PIPE_W + PIPE_LIP < b.x - 70:
                continue
            if not p.scored and p.x + PIPE_W < cx - r:
                p.scored = True
                self._score_pass()
            rects = (
                pygame.Rect(int(p.x), 0, PIPE_W, p.top),
                pygame.Rect(int(p.x) - PIPE_LIP, p.top - PIPE_CAP_H, PIPE_W + 2 * PIPE_LIP, PIPE_CAP_H),
                pygame.Rect(int(p.x) - PIPE_LIP, p.bottom, PIPE_W + 2 * PIPE_LIP, PIPE_CAP_H),
                pygame.Rect(int(p.x), p.bottom + PIPE_CAP_H, PIPE_W,
                            GROUND_TOP - p.bottom - PIPE_CAP_H),
            )
            for rect in rects:
                if _circle_rect(cx, b.y, r, rect):
                    self._handle_hit()
                    return
        if b.y + r >= GROUND_TOP:
            b.y = GROUND_TOP - r
            self._handle_hit()

    def update_dead(self, dt):
        b = self.bird
        if self.state_t >= 0.22:                 # brief freeze-frame on impact
            b.vy = min(b.vy + 2600.0 * dt, 950.0)
            b.y += b.vy * dt
            b.rot = min(90.0, b.rot + 520.0 * dt)
            if not self.landed and b.y + BIRD_HIT_R >= GROUND_TOP:
                b.y = GROUND_TOP - BIRD_HIT_R
                self.landed = True
                self.shake(6.0, 0.22)
                self.spawn_particles(10, (b.x, GROUND_TOP - 4),
                                     ((222, 198, 128), (188, 162, 104), (150, 132, 90)),
                                     (40, 130), (3, 6), (0.3, 0.6), 500.0)
        if self.state_t >= 1.25:
            self._finish_death()

    def update_gameover(self, dt):
        k = clamp(self.state_t / 0.45, 0.0, 1.0)
        e = 1.0 - (1.0 - k) ** 3
        self.panel_y = lerp(-220.0, 210.0, e)
        if len(self.buttons) == 2:
            self.buttons[0].rect.y = int(self.panel_y + 196)
            self.buttons[1].rect.y = int(self.panel_y + 252)

    # ------------------------------------------------------------------ #
    #  Per-frame step
    # ------------------------------------------------------------------ #
    def step(self, dt, fps_now):
        self.time += dt
        self.state_t += dt
        if self.state != "paused":
            self.menu_t += dt
            for c in self.clouds:
                c["x"] -= c["spd"] * dt
                if c["x"] < -180:
                    c["x"] = LOGICAL_W + random.uniform(20, 120)
                    c["y"] = random.uniform(26, GROUND_TOP - 190)
            if self.state in ("menu", "settings", "help"):
                self.world_x += 12.0 * dt
        d = self.night_target - self.night_blend
        self.night_blend += clamp(d, -0.8 * dt, 0.8 * dt)
        self.flash = max(0.0, self.flash - dt * 6.0)
        if self.shake_t > 0:
            self.shake_t = max(0.0, self.shake_t - dt)
        while self.sched and self.sched[0][0] <= self.time:
            self.audio.sfx(self.sched.pop(0)[1])

        if self.state == "ready":
            self.update_ready(dt)
        elif self.state == "playing":
            self.update_playing(dt)
        elif self.state == "dead":
            self.update_dead(dt)
        elif self.state == "gameover":
            self.update_gameover(dt)

        for p in self.particles:
            p["age"] += dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vy"] += p["g"] * dt
        self.particles = [p for p in self.particles if p["age"] < p["life"]]
        for pop in self.popups:
            pop[2] += dt
        self.popups = [p for p in self.popups if p[2] < 0.7]

        lp = self.mouse_logical(pygame.mouse.get_pos())
        for b in self.buttons:
            b.update(lp)

        self.draw(fps_now)

    # ------------------------------------------------------------------ #
    #  Drawing
    # ------------------------------------------------------------------ #
    def draw(self, fps_now):
        w = self.world
        ox, oy = self._shake_offset()
        w.fill((14, 16, 22))
        w.blit(self.sky_day, (ox, oy))
        if 0 < self.night_blend < 1.0:
            self.sky_night.set_alpha(int(self.night_blend * 255))
            w.blit(self.sky_night, (ox, oy))
        ca = int(255 * (1.0 - 0.55 * self.night_blend))
        for c in self.clouds:
            c["surf"].set_alpha(ca)
            w.blit(c["surf"], (int(c["x"]) + ox, int(c["y"]) + oy))

        in_run = self.state in ("ready", "playing", "dead", "gameover", "paused")
        if in_run:
            self._draw_pipe(w, self.pipe_skins[self.difficulty], ox, oy)
        ground_off = int(int(self.world_x) % 24)
        w.blit(self.ground, (-ground_off + ox, GROUND_TOP + oy))

        for p in self.particles:
            k = 1.0 - p["age"] / p["life"]
            sz = max(1, int(p["size"] * k))
            pygame.draw.rect(w, p["color"], (int(p["x"]) - sz // 2 + ox, int(p["y"]) - sz // 2 + oy, sz, sz))

        # -- the block-bird --
        if in_run:
            frame = self.frames["dead"] if self.bird.dead else self.frames[self.bird.wing]
            rot = self.bird.rot if self.state in ("playing", "dead", "gameover") else -18.0 + math.sin(self.time * 3.0) * 4
            bx, by = BIRD_X, self.bird.y
        else:
            birdy = 300 + math.sin(self.menu_t * 2.6) * 9
            frame = self.frames[("up", "mid", "down", "mid")[int(self.menu_t * 9) % 4]]
            rot, bx, by = 0.0, 255.0, birdy
        img = pygame.transform.rotate(frame, -rot) if abs(rot) > 0.05 else frame
        w.blit(img, img.get_rect(center=(int(bx) + ox, int(by) + oy)))

        self.screen.blit(w, (0, 0))
        s = self.screen

        # -- HUD / overlays (world-unshaken) --
        if in_run:
            s.blit(self.s_best, (12, 10))
            s.blit(self.s_mode, (LOGICAL_W - self.s_mode.get_width() - 12, 12))
        if self.state in ("playing", "dead", "gameover", "paused"):
            self._draw_score(s)
            if self.exceeded_best and self.state == "playing":
                s.blit(self.s_newbest, (200 - self.s_newbest.get_width() // 2, 84))
        for pop in self.popups:
            s.blit(self.s_plus, (int(pop[0]), int(pop[1] - pop[2] * 55)))

        if self.state == "ready":
            s.blit(self.s_getready, (200 - self.s_getready.get_width() // 2, 168))
            ay = int(self.bird.y - 44 + math.sin(self.time * 6.0) * 4)
            pts = [(int(BIRD_X) + 54, ay - 9), (int(BIRD_X) + 66, ay + 2), (int(BIRD_X) + 42, ay + 2)]
            pygame.draw.polygon(s, (30, 30, 36), [(x + 2, y + 2) for x, y in pts])
            pygame.draw.polygon(s, (255, 255, 255), pts)
            s.blit(self.s_hint, (200 - self.s_hint.get_width() // 2, 212))

        if self.state == "menu":
            self._draw_title(s)
            s.blit(self.s_best, (200 - self.s_best.get_width() // 2, 512))
            s.blit(self.s_footer1, (200 - self.s_footer1.get_width() // 2, 646))
            s.blit(self.s_footer2, (200 - self.s_footer2.get_width() // 2, 666))
        elif self.state == "paused":
            dim = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
            dim.fill((15, 18, 26, 150))
            s.blit(dim, (0, 0))
            s.blit(self.s_paused, (200 - self.s_paused.get_width() // 2, 186))
            s.blit(self.s_paused_hint, (200 - self.s_paused_hint.get_width() // 2, 434))
        elif self.state == "settings":
            self._draw_panel(s, (50, 118, 300, 314))
            s.blit(self.s_settings, (200 - self.s_settings.get_width() // 2, 134))
            l = text(22, "MUSIC", (66, 54, 40), (255, 255, 255))
            s.blit(l, (84, 172))
            l = text(22, "SFX", (66, 54, 40), (255, 255, 255))
            s.blit(l, (84, 232))
        elif self.state == "help":
            self._draw_panel(s, (50, 80, 300, 444))
            s.blit(self.s_howto, (200 - self.s_howto.get_width() // 2, 96))
            y = 140
            for line in self.help_lines:
                s.blit(line, (74, y))
                y += 30
            for i, (_t, name, _c) in enumerate(reversed(MEDALS)):
                m = self.medals_small[name]
                s.blit(m, (88 + i * 58, y))
                num = self.help_medal_nums[i]
                s.blit(num, (108 + i * 58 - num.get_width() // 2, y + 46))
            s.blit(self.help_credits, (74, 430))
        elif self.state == "gameover":
            self._draw_gameover(s)

        # buttons last (always crisp, top-most)
        if self.state in ("menu", "settings", "help", "paused", "gameover"):
            for btn in self.buttons:
                btn.draw(s)

        if self.state == "dead" and self.flash > 0:
            fl = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
            fl.fill((255, 255, 255, int(self.flash * 160)))
            s.blit(fl, (0, 0))

        if self.show_fps:
            fps_t = text(18, f"{int(fps_now)} FPS", (200, 205, 215), (30, 30, 40))
            s.blit(fps_t, (LOGICAL_W - fps_t.get_width() - 8, LOGICAL_H - fps_t.get_height() - 6))

        # composite: letterbox scale logical canvas -> window
        self.window.fill((8, 9, 12))
        scaled = pygame.transform.scale(self.screen, (self.w0, self.h0))
        self.window.blit(scaled, (self.ox, self.oy))
        pygame.display.flip()

    def _draw_panel(self, s, rect):
        dim = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
        dim.fill((10, 12, 18, 150))
        s.blit(dim, (0, 0))
        pygame.draw.rect(s, (247, 239, 214), rect, border_radius=14)
        pygame.draw.rect(s, (120, 84, 30), rect, width=3, border_radius=14)

    def _draw_title(self, s):
        total = self.title_width
        x = 200 - total // 2
        for i, letter in enumerate(self.title_letters):
            yoff = int(math.sin(self.menu_t * 2.4 + i * 0.55) * 4)
            s.blit(letter, (x, 84 + yoff))
            x += letter.get_width()
        s.blit(self.s_extreme, (200 - self.s_extreme.get_width() // 2, 138))

    def _draw_score(self, s):
        digits = [self.digits[int(c)] for c in str(self.score)]
        total = sum(d.get_width() for d in digits)
        x = 200 - total // 2
        for d in digits:
            s.blit(d, (x, 26))
            x += d.get_width()

    def _draw_gameover(self, s):
        dim = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
        dim.fill((20, 22, 30, 80))
        s.blit(dim, (0, 0))
        y = int(self.panel_y)
        pygame.draw.rect(s, (247, 239, 214), (50, y, 300, 178), border_radius=14)
        pygame.draw.rect(s, (120, 84, 30), (50, y, 300, 178), width=3, border_radius=14)
        s.blit(self.s_gameoverhead, (200 - self.s_gameoverhead.get_width() // 2, y + 12))
        if self.medal:
            m = self.medals_small[self.medal]
            s.blit(m, (110 - m.get_width() // 2, y + 58))
            nm = text(18, self.medal, (90, 60, 25), (255, 255, 255))
            s.blit(nm, (110 - nm.get_width() // 2, y + 126))
        else:
            nm = text(18, "NO MEDAL", (150, 140, 120), (255, 255, 255))
            s.blit(nm, (110 - nm.get_width() // 2, y + 96))
        lab1 = text(20, "SCORE", (140, 100, 45), (255, 255, 255))
        s.blit(lab1, (258 - lab1.get_width() // 2, y + 52))
        num = self._score_surface_small()
        s.blit(num, (258 - num.get_width() // 2, y + 72))
        lab2 = text(20, "BEST", (140, 100, 45), (255, 255, 255))
        s.blit(lab2, (258 - lab2.get_width() // 2, y + 118))
        best_s = text(42, str(self.best[self.difficulty]), (216, 110, 40), (255, 255, 255))
        s.blit(best_s, (258 - best_s.get_width() // 2, y + 136))
        if self.new_best:
            s.blit(self.s_newbest, (258 + best_s.get_width() // 2 + 10, y + 146))

    def _score_surface_small(self):
        d = [self.digits[int(c)] for c in str(self.score)]
        total = sum(x.get_width() for x in d)
        hh = max(x.get_height() for x in d)
        out = pygame.Surface((total, hh), pygame.SRCALPHA)
        x = 0
        for dig in d:
            out.blit(dig, (x, 0))
            x += dig.get_width()
        return out


# --------------------------------------------------------------------------- #
#  Main loop & events
# --------------------------------------------------------------------------- #
class _WrappedEvent:
    """Adds the classic repeat flag to events (pygame-ce's Event has no such
    attribute). A KEYDOWN emulates old behaviour: it is a repeat if that key
    is already held in keys_down. All other attributes pass through."""
    __slots__ = ("_e", "repeat")

    def __init__(self, e, keys_down):
        self._e = e
        self.repeat = bool(getattr(e, "repeat", False))
        if e.type == pygame.KEYDOWN:
            if e.key in keys_down:
                self.repeat = True
            else:
                keys_down.add(e.key)
        elif e.type == pygame.KEYUP:
            keys_down.discard(e.key)

    def __getattr__(self, name):
        return getattr(self._e, name)


def main():
    pygame.mixer.pre_init(44100, -16, 1, 2048)
    ok = pygame.init()
    failed = [] if ok else list(pygame.get_init()[1])
    try:
        pygame.display.set_mode((LOGICAL_W, LOGICAL_H), pygame.RESIZABLE)
    except pygame.error as exc:
        sys.exit(f"Could not open a window ({exc}). "
                 "If you are on an SSH/VPS session you need a display "
                 "(X11 / VNC / X forwarding).\n"
                 f"SDL_VIDEODRIVER=dummy can be used for headless audio tests only.")
    pygame.display.set_caption("FlippyBlock EXTREME")
    try:
        icon = pygame.Surface((32, 32), pygame.SRCALPHA)
        pygame.draw.rect(icon, (52, 40, 22), (1, 1, 30, 30), border_radius=9)
        pygame.draw.rect(icon, (255, 201, 64), (3, 3, 26, 26), border_radius=7)
        pygame.draw.rect(icon, (233, 158, 40), (4, 17, 24, 11), border_radius=5)
        pygame.draw.circle(icon, (255, 255, 255), (21, 11), 6)
        pygame.draw.circle(icon, (40, 40, 40), (23, 11), 3)
        pygame.draw.rect(icon, (250, 250, 250), (7, 14, 12, 8), border_radius=4)
        pygame.display.set_icon(icon)
    except (pygame.error, AttributeError):
        pass

    game = Game()
    clock = pygame.time.Clock()
    keys_down = set()  
    mouse_down = False

    while game.running:
        dt = min(clock.tick(FPS) / 1000.0, 1.0 / 20.0)   # clamp dt: no tunneling on lag spikes
        for event in (_WrappedEvent(e, keys_down) for e in pygame.event.get()):
            if event.type == pygame.QUIT:
                game.running = False
            elif event.type == pygame.VIDEORESIZE:
                game.window = pygame.display.get_surface()
                game._fit_window()
            elif event.type == pygame.WINDOWFOCUSLOST:
                keys_down.clear()
                game.pause()                            # auto-pause when the window loses focus
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                lp = game.mouse_logical(event.pos)
                if not game._in_logical(lp):
                    continue
                if game.state in ("ready", "playing"):
                    if not event.repeat:
                        game.do_flap()
                elif game.state == "gameover" and game.state_t > 0.45:
                    for b in game.buttons:
                        if b.rect.collidepoint(lp):
                            game.audio.sfx("click")
                            b.action()
                            break
                else:
                    for b in game.buttons:
                        if b.rect.collidepoint(lp):
                            game.audio.sfx("click")
                            b.action()
                            break
            elif event.type == pygame.KEYDOWN:
                k = event.key
                if event.repeat or k == pygame.K_m:
                    pass  # handled below for M; skip repeats
                if not event.repeat:
                    if k == pygame.K_m:
                        game.toggle_mute()
                        continue
                    if k == pygame.K_F11:
                        game.toggle_fullscreen()
                        continue
                    if game.state == "menu":
                        if k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                            game.audio.sfx("click")
                            game.start_run()
                    elif game.state in ("settings", "help"):
                        if k in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                            game.show_menu()
                    elif game.state == "paused":
                        if k in (pygame.K_p, pygame.K_ESCAPE):
                            game.resume()
                    elif game.state == "ready":
                        if k in (pygame.K_SPACE, pygame.K_UP, pygame.K_w,
                                 pygame.K_RETURN, pygame.K_KP_ENTER):
                            game.do_flap()
                        elif k in (pygame.K_p, pygame.K_ESCAPE):
                            game.pause()
                    elif game.state == "playing":
                        if k in (pygame.K_SPACE, pygame.K_UP, pygame.K_w):
                            game.do_flap()
                        elif k in (pygame.K_p, pygame.K_ESCAPE):
                            game.pause()
                    elif game.state == "dead":
                        if k == pygame.K_r and game.state_t > 0.5:
                            game.start_run()
                        elif k == pygame.K_ESCAPE and game.state_t > 0.2:
                            game.show_menu()
                    elif game.state == "gameover":
                        if k in (pygame.K_r, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                            game.start_run()
                        elif k == pygame.K_ESCAPE:
                            game.show_menu()
        if game.running:
            game.step(dt, clock.get_fps())

    game._save()
    pygame.quit()


if __name__ == "__main__":
    main()
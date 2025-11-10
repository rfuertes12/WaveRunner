import math
import random
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pygame

# --- Game Config ---
WIDTH, HEIGHT = 960, 540
FPS = 60
WATERLINE = HEIGHT * 0.62
WAVE_POINTS = 160          # fidelity of the water mesh
WAVE_SPEED = 0.95          # global wave phase speed
BASE_AMPLITUDE = 46        # base wave height
AMPLITUDE_SWAY = 30        # extra amplitude that swells over time
WAVELENGTH = 220           # distance between crests

PLAYER_RADIUS = 14
PLAYER_GRAVITY = 0.75
JUMP_VELOCITY = -12
DOUBLE_JUMP_MULTIPLIER = 2.0
DOUBLE_TAP_WINDOW = 0.28

ENEMY_COLOR = (64, 200, 255)
ENEMY_SPAWN_EVERY = 1.25   # seconds between enemy waves
ENEMY_MIN_SPEED = 2.8
ENEMY_MAX_SPEED = 5.2
ENEMY_RADIUS = 14

PULSE_COLOR = (120, 220, 255)
PULSE_RADIUS_MAX = 260
PULSE_THICKNESS = 4
PULSE_ENERGY_MAX = 100
PULSE_GAIN_ON_HIT = 28

HARPOON_SPEED = 620
HARPOON_COOLDOWN = 0.45

BUOY_DRIFT_SPEED = 36

SPECIAL_CATCH_CHANCE = 0.22
SPECIAL_MAX_STOCK = 5

BACKGROUND_TOP = (6, 26, 48)
BACKGROUND_BOTTOM = (4, 10, 22)
WATER_TOP = (32, 158, 206)
WATER_BOTTOM = (4, 64, 122)
WATER_GLOW = (18, 96, 168)
SPRAY_COLOR = (220, 250, 255)
UI_PANEL = (12, 28, 54, 210)
UI_ACCENT = (96, 222, 255)
UI_TEXT = (236, 248, 255)
UI_MUTED = (120, 160, 188)

pygame.init()
pygame.font.init()
try:
    pygame.mixer.init()
except pygame.error:
    # Running without audio is fine when a device isn't present.
    pygame.mixer = None  # type: ignore

screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("WaveRunner: Tidal Tactician")
clock = pygame.time.Clock()
font = pygame.font.SysFont("bahnschrift", 22)
large_font = pygame.font.SysFont("bahnschrift", 32, bold=True)


# --- Helpers ---
def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def generate_wave_y(x: float, phase: float, t: float) -> float:
    """Compute water surface Y at X using multiple sine layers."""
    k = (2 * math.pi) / WAVELENGTH
    a = BASE_AMPLITUDE + AMPLITUDE_SWAY * (0.5 + 0.5 * math.sin(t * 0.3))
    y = WATERLINE + a * math.sin(k * x + phase)
    y += 0.33 * a * math.sin(0.5 * k * x - 0.7 * phase + t * 0.6)
    y += 0.12 * a * math.sin(1.7 * k * x + 1.9 * phase)
    return y


def build_wave_mesh(phase: float, t: float) -> List[Tuple[float, float]]:
    pts = []
    step = WIDTH / WAVE_POINTS
    for i in range(WAVE_POINTS + 1):
        x = i * step
        y = generate_wave_y(x, phase, t)
        pts.append((x, y))
    return pts


def create_tone(freq: int, duration: float = 0.12, volume: float = 0.4):
    if not pygame.mixer or not pygame.mixer.get_init():
        return None
    sample_rate = 44100
    sample_count = int(duration * sample_rate)
    buf = bytearray()
    for i in range(sample_count):
        t = i / sample_rate
        sample = int(32767 * math.sin(2 * math.pi * freq * t))
        buf += int(sample).to_bytes(2, byteorder="little", signed=True)
    sound = pygame.mixer.Sound(buffer=bytes(buf))
    sound.set_volume(volume)
    return sound


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "start_life")

    def __init__(self, x: float, y: float, vx: float, vy: float, life: float = 0.8):
        self.x, self.y, self.vx, self.vy, self.life = x, y, vx, vy, life
        self.start_life = life

    def update(self, dt: float) -> None:
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += 40 * dt
        self.life -= dt

    def draw(self, surf: pygame.Surface) -> None:
        if self.life <= 0:
            return
        fade = max(0.0, min(1.0, self.life / self.start_life))
        color = (
            int(SPRAY_COLOR[0] * fade + 55 * (1 - fade)),
            int(SPRAY_COLOR[1] * fade + 80 * (1 - fade)),
            int(SPRAY_COLOR[2] * fade + 110 * (1 - fade)),
        )
        pygame.draw.circle(surf, color, (int(self.x), int(self.y)), 2)


class Pulse:
    def __init__(self, x: float, y: float):
        self.x, self.y = x, y
        self.r = 0.0
        self.alive = True

    def update(self, dt: float) -> None:
        self.r += 320 * dt
        if self.r > PULSE_RADIUS_MAX:
            self.alive = False

    def draw(self, surf: pygame.Surface) -> None:
        if self.r > 2:
            pygame.draw.circle(
                surf, PULSE_COLOR, (int(self.x), int(self.y)), int(self.r), PULSE_THICKNESS
            )


class Harpoon:
    def __init__(self, x: float, y: float, direction: int):
        self.x = x
        self.y = y
        self.direction = direction
        self.vx = HARPOON_SPEED * direction
        self.alive = True

    def update(self, dt: float) -> None:
        self.x += self.vx * dt
        self.y += math.sin(pygame.time.get_ticks() * 0.002 + self.x * 0.01) * 10 * dt
        if self.x < -60 or self.x > WIDTH + 60:
            self.alive = False

    def draw(self, surf: pygame.Surface) -> None:
        if not self.alive:
            return
        color = (222, 244, 255)
        points = [
            (self.x, self.y),
            (self.x - 16 * self.direction, self.y - 2),
            (self.x - 16 * self.direction, self.y + 2),
        ]
        pygame.draw.polygon(surf, color, points)
        pygame.draw.line(
            surf,
            (140, 210, 255),
            (self.x - 16 * self.direction, self.y),
            (self.x - 24 * self.direction, self.y),
            2,
        )


class Enemy:
    VARIANT_COLORS = {
        "standard": ENEMY_COLOR,
        "hopper": (88, 236, 196),
        "diver": (180, 132, 255),
        "charger": (255, 140, 130),
    }

    def __init__(self, x: float, speed: float, variant: str):
        self.x = x
        self.speed = speed
        self.variant = variant
        self.alive = True
        self.t = 0.0
        self.y = WATERLINE
        self.warning = 0.4
        self.wave_offset = random.uniform(0, math.pi * 2)

    def update(self, dt: float, phase: float, t: float) -> None:
        self.t += dt
        self.x -= self.speed * 60 * dt
        wave_y = generate_wave_y(self.x, phase, t)

        if self.variant == "hopper":
            hop = math.sin(self.t * 3.4) * 30 * max(0.0, 1.0 - self.warning * 2)
            self.y = wave_y - 6 - hop
        elif self.variant == "diver":
            dive = math.sin(self.t * 2.2 + 1.2) * 18
            self.y = wave_y - 6 + dive
        elif self.variant == "charger":
            dive = math.sin(self.t * 6.0 + self.wave_offset) * 6
            self.y = wave_y - 12 + dive
            self.speed *= 1.005
        else:
            self.y = wave_y - 6

        if self.x < -40:
            self.alive = False

        if self.warning > 0:
            self.warning -= dt

    def draw(self, surf: pygame.Surface) -> None:
        color = self.VARIANT_COLORS.get(self.variant, ENEMY_COLOR)
        px = int(self.x)
        py = int(self.y)
        body_length = ENEMY_RADIUS * 3
        body_height = ENEMY_RADIUS * 1.4
        body_rect = pygame.Rect(0, 0, body_length, int(body_height))
        body_rect.center = (px, py)
        fish_surface = pygame.Surface((body_length + 20, int(body_height) + 20), pygame.SRCALPHA)
        local_rect = body_rect.copy()
        local_rect.center = (fish_surface.get_width() // 2, fish_surface.get_height() // 2)
        pygame.draw.ellipse(fish_surface, color, local_rect)

        tail_points = [
            (local_rect.left, local_rect.centery - body_height * 0.9),
            (local_rect.left - body_length * 0.3, local_rect.centery),
            (local_rect.left, local_rect.centery + body_height * 0.9),
        ]
        pygame.draw.polygon(fish_surface, color, tail_points)

        eye_x = local_rect.right - body_length * 0.35
        eye_y = local_rect.centery - body_height * 0.15
        pygame.draw.circle(fish_surface, (12, 28, 48), (int(eye_x), int(eye_y)), 3)
        pygame.draw.circle(fish_surface, (240, 252, 255), (int(eye_x) + 1, int(eye_y) - 1), 1)

        surf.blit(
            fish_surface,
            (
                px - fish_surface.get_width() // 2,
                py - fish_surface.get_height() // 2,
            ),
        )

        if self.warning > 0:
            alpha = int(200 * (self.warning / 0.4))
            overlay_color = (*color, alpha)
            flash_surface = pygame.Surface(
                (body_length + 28, int(body_height) + 28), pygame.SRCALPHA
            )
            pygame.draw.ellipse(flash_surface, overlay_color, flash_surface.get_rect(), 6)
            surf.blit(
                flash_surface,
                (
                    px - flash_surface.get_width() // 2,
                    py - flash_surface.get_height() // 2,
                ),
            )

    def hit_by_pulse(self, pulse: "Pulse") -> bool:
        if not pulse.alive:
            return False
        dx = self.x - pulse.x
        dy = self.y - pulse.y
        return dx * dx + dy * dy <= (pulse.r + ENEMY_RADIUS) ** 2


class Player:
    def __init__(self):
        self.anchor_x = WIDTH * 0.3
        self.x = self.anchor_x
        self.y = generate_wave_y(self.anchor_x, 0.0, 0.0) - 22
        self.vy = 0.0
        self.health = 3
        self.iframes = 0.0
        self.score = 0.0
        self.combo = 0
        self.best_combo = 0
        self.last_combo_time = 0.0
        self.facing = 1

    def snap_to_wave(self, phase: float, t: float) -> None:
        target = generate_wave_y(self.anchor_x, phase, t) - 22
        self.y = target
        self.vy = 0.0

    def update(
        self,
        dt: float,
        phase: float,
        t: float,
        _particles: List[Particle],
        _jump_request: Optional[str],
    ) -> None:
        self.x = self.anchor_x
        wave_y = generate_wave_y(self.x, phase, t)
        target = wave_y - 22

        delta = target - self.y
        self.vy += delta * 0.12
        self.vy *= 0.88
        self.y += self.vy * dt * 60

        if abs(delta) < 0.4 and abs(self.vy) < 0.15:
            self.y = target
            self.vy = 0.0

        if self.iframes > 0:
            self.iframes -= dt

        self.score += dt * 4 * (1 + self.combo * 0.02)
        self.last_combo_time += dt
        self.facing = 1

    def draw(self, surf: pygame.Surface) -> None:
        flicker = self.iframes > 0 and int(pygame.time.get_ticks() * 0.02) % 2 == 0
        base_color = (232, 240, 252) if not flicker else (120, 140, 160)
        coat_color = (44, 84, 120)
        hat_color = (240, 176, 92)
        rod_color = (190, 230, 255)

        px = int(self.x)
        py = int(self.y)
        facing = self.facing

        hull_color = (92, 58, 30)
        trim_color = (180, 132, 92)
        hull_rect = pygame.Rect(0, 0, 72, 20)
        hull_rect.center = (px, py + 24)
        pygame.draw.ellipse(surf, hull_color, hull_rect)
        pygame.draw.ellipse(surf, trim_color, hull_rect.inflate(-12, -6), 3)

        bow = [
            (hull_rect.right - 4, hull_rect.centery - 10),
            (hull_rect.right + 10, hull_rect.centery),
            (hull_rect.right - 4, hull_rect.centery + 10),
        ]
        pygame.draw.polygon(surf, hull_color, bow)

        stern = [
            (hull_rect.left + 4, hull_rect.centery - 10),
            (hull_rect.left - 10, hull_rect.centery - 4),
            (hull_rect.left + 4, hull_rect.centery + 10),
        ]
        pygame.draw.polygon(surf, hull_color, stern)

        mast = pygame.Rect(0, 0, 6, 32)
        mast.center = (px, py)
        pygame.draw.rect(surf, (158, 188, 210), mast, border_radius=3)
        pennant = [
            (mast.right, mast.top + 6),
            (mast.right + 18, mast.top + 10),
            (mast.right, mast.top + 16),
        ]
        pygame.draw.polygon(surf, (230, 90, 96), pennant)

        body_rect = pygame.Rect(0, 0, 18, 26)
        body_rect.center = (px, py)
        pygame.draw.rect(surf, coat_color, body_rect, border_radius=4)

        head_rect = pygame.Rect(0, 0, 16, 16)
        head_rect.center = (px, py - 18)
        pygame.draw.rect(surf, base_color, head_rect, border_radius=3)

        brim = pygame.Rect(0, 0, 20, 6)
        brim.center = (px, py - 24)
        pygame.draw.rect(surf, hat_color, brim, border_radius=3)
        crown = pygame.Rect(0, 0, 14, 8)
        crown.center = (px, py - 30)
        pygame.draw.rect(surf, hat_color, crown, border_radius=3)

        arm_offset = 12 * facing
        pygame.draw.line(
            surf,
            base_color,
            (px, py - 2),
            (px + arm_offset, py + 4),
            4,
        )
        pygame.draw.line(
            surf,
            rod_color,
            (px + arm_offset, py + 4),
            (px + arm_offset + 16 * facing, py - 24),
            2,
        )

    def damage(self) -> None:
        if self.iframes <= 0:
            self.health -= 1
            self.iframes = 1.0
            self.combo = 0
            self.last_combo_time = 0.0

    def reward_combo(self, amount: int) -> None:
        self.combo = min(99, self.combo + amount)
        self.best_combo = max(self.best_combo, self.combo)
        self.last_combo_time = 0.0


class Buoy:
    def __init__(self, x: float, y: float, target_x: float):
        self.base_x = x
        self.x = x
        self.y = y
        self.target_x = target_x
        self.phase = random.uniform(0, math.pi * 2)

    def update(self, dt: float, phase: float, t: float) -> None:
        self.phase += dt * 1.6
        direction = -1 if self.base_x > self.target_x else 1
        self.base_x += direction * BUOY_DRIFT_SPEED * dt
        self.base_x = lerp(self.base_x, self.target_x, 0.4 * dt)
        drift = math.sin(self.phase * 0.7) * 22
        self.x = self.base_x + drift
        crest = generate_wave_y(self.x, phase, t)
        crest += math.sin((t + self.phase) * 1.8) * 6
        self.y = crest - 30 + math.sin(self.phase * 1.5) * 5

    def draw(self, surf: pygame.Surface) -> None:
        pole_color = (200, 220, 230)
        float_color = (248, 160, 48)
        band_color = (230, 64, 64)

        px = int(self.x)
        py = int(self.y)

        pygame.draw.line(surf, pole_color, (px, py - 40), (px, py - 10), 4)
        pygame.draw.circle(surf, pole_color, (px, py - 48), 6)
        pygame.draw.circle(surf, (240, 200, 72), (px, py - 48), 3)

        body_rect = pygame.Rect(0, 0, 38, 24)
        body_rect.center = (px, py)
        pygame.draw.ellipse(surf, float_color, body_rect)
        pygame.draw.ellipse(surf, band_color, body_rect.inflate(-6, -12))

        glow = pygame.Surface((70, 70), pygame.SRCALPHA)
        pygame.draw.circle(glow, (240, 200, 72, 90), (35, 35), 30)
        surf.blit(glow, glow.get_rect(center=(px, py - 42)))

    def collected_by(self, px: float, py: float) -> bool:
        dx = px - self.x
        dy = (py + 10) - self.y
        return dx * dx + dy * dy <= 40 ** 2


class SpecialCatch:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y
        self.phase = random.uniform(0, math.pi * 2)
        self.float_offset = random.uniform(-18, 18)
        self.collected = False

    def update(self, dt: float, phase: float, t: float, target_x: float) -> None:
        self.phase += dt * 2.4
        self.x += (target_x - self.x) * dt * 2.0
        crest = generate_wave_y(self.x, phase, t)
        wobble = math.sin(self.phase) * 8
        self.y = crest - 26 + wobble + self.float_offset

    def collected_by(self, px: float, py: float) -> bool:
        if self.collected:
            return False
        dx = px - self.x
        dy = (py - 8) - self.y
        if dx * dx + dy * dy <= 26 ** 2:
            self.collected = True
        return self.collected

    def draw(self, surf: pygame.Surface) -> None:
        glow = pygame.Surface((40, 40), pygame.SRCALPHA)
        pygame.draw.circle(glow, (140, 220, 255, 110), (20, 20), 18)
        pygame.draw.circle(glow, (240, 255, 170, 190), (20, 20), 10)
        pygame.draw.circle(glow, (255, 255, 255, 220), (20, 20), 6)
        surf.blit(glow, glow.get_rect(center=(int(self.x), int(self.y))))


@dataclass
class ComboPopup:
    text: pygame.Surface
    pos: pygame.Vector2
    ttl: float

    def update(self, dt: float):
        self.ttl -= dt
        self.pos.y -= 24 * dt

    def draw(self, surf: pygame.Surface):
        surf.blit(self.text, self.pos)


class Game:
    def __init__(self):
        self.screen = screen
        self.clock = clock
        self.font = font
        self.title_font = large_font
        self.sky_surface = self._build_sky()
        self.combo_popups: List[ComboPopup] = []
        self.hit_sound = create_tone(220, duration=0.18, volume=0.5)
        self.pulse_sound = create_tone(660, duration=0.1, volume=0.35)
        self.score_sound = create_tone(440, duration=0.12, volume=0.4)
        self.special_sound = create_tone(880, duration=0.16, volume=0.35)

        self.state = "intro"
        self.state_timer = 0.0
        self.paused = False
        self.pause_rect = pygame.Rect(WIDTH - 132, 96, 100, 32)
        self.pending_shot = False
        self.pending_pulse = False
        self.pending_special = False
        self.high_score = 0
        self.buoy: Optional[Buoy] = None
        self.awaiting_buoy = False
        self.spawner_phase = 0.0
        self.special_catches: List[SpecialCatch] = []
        self.special_stock = 0
        self.jump_request: Optional[str] = None
        self.last_space_press = -10.0
        self.reset()

    def _build_sky(self) -> pygame.Surface:
        surf = pygame.Surface((WIDTH, HEIGHT))
        for i in range(HEIGHT):
            t = i / HEIGHT
            r = int(lerp(BACKGROUND_TOP[0], BACKGROUND_BOTTOM[0], t))
            g = int(lerp(BACKGROUND_TOP[1], BACKGROUND_BOTTOM[1], t))
            b = int(lerp(BACKGROUND_TOP[2], BACKGROUND_BOTTOM[2], t))
            pygame.draw.line(surf, (r, g, b), (0, i), (WIDTH, i))
        return surf.convert()

    def reset(self):
        self.player = Player()
        self.enemies: List[Enemy] = []
        self.particles: List[Particle] = []
        self.pulses: List[Pulse] = []
        self.harpoons: List[Harpoon] = []
        self.special_catches = []
        self.spawn_timer = 0.0
        self.shoot_timer = 0.0
        self.pulse_energy = PULSE_ENERGY_MAX * 0.6
        self.runtime = 0.0
        self.phase = 0.0
        self.combo_popups.clear()
        self.state = "intro"
        self.state_timer = 0.0
        self.paused = False
        self.stage = 1
        self.kills_this_stage = 0
        self.stage_goal = self._goal_for_stage(self.stage)
        self.stage_banner_timer = 3.0
        self.stage_banner_text = f"Stage {self.stage}: Dawn Swell"
        self.spawn_interval = ENEMY_SPAWN_EVERY
        self.pending_shot = False
        self.pending_pulse = False
        self.pending_special = False
        self.buoy = None
        self.awaiting_buoy = False
        self.spawner_phase = 0.0
        self.special_stock = 0
        self.jump_request = None
        self.last_space_press = -10.0
        self.player.snap_to_wave(self.phase, self.runtime)

    def spawn_enemy_wave(self):
        stage_factor = min(self.stage, 12)
        n = random.randint(3, 4 + stage_factor // 2)
        spacing = random.randint(22, 40)
        start_x = WIDTH + 50
        speed_boost = 0.9 + (stage_factor - 1) * 0.08
        base_speed = random.uniform(ENEMY_MIN_SPEED, ENEMY_MAX_SPEED) * speed_boost
        variants = ["standard", "hopper", "diver", "charger"]
        weights = [0.45, 0.22, 0.2, min(0.18 + 0.025 * stage_factor, 0.42)]
        for i in range(n):
            variant = random.choices(variants, weights=weights)[0]
            jitter = random.uniform(0.88, 1.12)
            enemy = Enemy(start_x + i * spacing, base_speed * jitter, variant)
            self.enemies.append(enemy)

        spawner_x = WIDTH - 48
        spawner_y = generate_wave_y(WIDTH + 20, self.phase, self.runtime)
        for _ in range(8):
            ang = random.uniform(-0.4, 0.4)
            speed = random.uniform(90, 140)
            self.particles.append(
                Particle(
                    spawner_x + random.uniform(-10, 10),
                    spawner_y - random.uniform(10, 30),
                    -speed * abs(math.cos(ang)) * random.uniform(0.8, 1.1),
                    -speed * math.sin(ang),
                    life=0.8,
                )
            )

    def _goal_for_stage(self, stage: int) -> int:
        return 8 + stage * 4

    def _stage_name(self, stage: int) -> str:
        names = [
            "Dawn Swell",
            "Azure Rush",
            "Breaker Bloom",
            "Gale Current",
            "Vortex Tide",
            "Stormglass",
            "Moonlit Surge",
            "Tempest Rise",
            "Celestial Reef",
            "Mythic Maelstrom",
        ]
        return names[min(stage - 1, len(names) - 1)]

    def add_combo_popup(self, text: str, x: float, y: float):
        surf = self.font.render(text, True, UI_ACCENT)
        popup = ComboPopup(surf, pygame.Vector2(x - surf.get_width() / 2, y - 30), 0.9)
        self.combo_popups.append(popup)

    def handle_events(self) -> bool:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    now = pygame.time.get_ticks() / 1000.0
                    if now - self.last_space_press <= DOUBLE_TAP_WINDOW:
                        self.jump_request = "double"
                    else:
                        self.jump_request = "single"
                    self.last_space_press = now
                elif event.key in (pygame.K_w, pygame.K_UP):
                    self.jump_request = "single"
                elif event.key == pygame.K_f:
                    self.pending_special = True
                elif event.key == pygame.K_r:
                    self.reset()
                elif event.key == pygame.K_RETURN and self.state == "intro":
                    self.state = "gameplay"
                elif event.key == pygame.K_p:
                    self.paused = not self.paused
                elif event.key == pygame.K_ESCAPE:
                    self.paused = not self.paused
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.pause_rect.collidepoint(event.pos):
                    self.paused = not self.paused
                else:
                    self.pending_shot = True
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                self.pending_pulse = True
        return True

    def update(self, dt: float):
        self.state_timer += dt
        if self.state == "intro" and self.state_timer > 2.5:
            self.state = "gameplay"

        if self.state != "gameplay":
            self.pending_shot = False
            self.pending_pulse = False
            self.pending_special = False
            return

        if self.stage_banner_timer > 0:
            dec = 0.0 if self.paused else dt
            self.stage_banner_timer = max(0.0, self.stage_banner_timer - dec)

        if self.paused:
            self.pending_shot = False
            self.pending_pulse = False
            self.pending_special = False
            return

        self.runtime += dt
        self.phase += WAVE_SPEED * dt
        self.spawner_phase = (self.spawner_phase + dt) % (math.pi * 2)

        self.shoot_timer = max(0.0, self.shoot_timer - dt)
        if self.pending_shot and self.shoot_timer <= 0.0:
            self.fire_harpoon()
        self.pending_shot = False

        self.pulse_energy = min(PULSE_ENERGY_MAX, self.pulse_energy + dt * 8)
        if self.pending_pulse and self.pulse_energy >= PULSE_ENERGY_MAX:
            self.pulses.append(Pulse(self.player.x, self.player.y))
            self.pulse_energy = 0.0
            if self.pulse_sound:
                self.pulse_sound.play()
        self.pending_pulse = False

        mesh = build_wave_mesh(self.phase, self.runtime)
        self.wave_mesh = mesh

        jump = self.jump_request
        self.jump_request = None
        self.player.update(dt, self.phase, self.runtime, self.particles, jump)

        self.spawn_timer += dt
        if self.spawn_timer >= self.spawn_interval:
            self.spawn_timer = 0.0
            self.spawn_enemy_wave()

        for enemy in self.enemies:
            enemy.update(dt, self.phase, self.runtime)

        for pulse in self.pulses:
            pulse.update(dt)

        for harpoon in self.harpoons:
            harpoon.update(dt)

        if self.buoy:
            self.buoy.update(dt, self.phase, self.runtime)

        for catch in self.special_catches:
            catch.update(dt, self.phase, self.runtime, self.player.x)

        for enemy in self.enemies:
            if not enemy.alive:
                continue
            dx = enemy.x - self.player.x
            dy = enemy.y - self.player.y
            if dx * dx + dy * dy <= (ENEMY_RADIUS + PLAYER_RADIUS) ** 2:
                self.player.damage()
                enemy.alive = False
                if self.hit_sound:
                    self.hit_sound.play()
                if self.player.health <= 0:
                    self.state = "game_over"
                continue

            for harpoon in self.harpoons:
                if harpoon.alive and enemy.alive:
                    hx = enemy.x - harpoon.x
                    hy = enemy.y - harpoon.y
                    if hx * hx + hy * hy <= (ENEMY_RADIUS + 6) ** 2:
                        enemy.alive = False
                        harpoon.alive = False
                        self.player.reward_combo(1)
                        reward = 60 + 16 * self.player.combo
                        self.player.score += reward
                        self.add_combo_popup(f"Harpoon +{reward}", enemy.x, enemy.y)
                        self.pulse_energy = min(
                            PULSE_ENERGY_MAX, self.pulse_energy + PULSE_GAIN_ON_HIT
                        )
                        self.kills_this_stage += 1
                        self._maybe_spawn_special(enemy.x, enemy.y)
                        if self.score_sound:
                            self.score_sound.play()
                        self._check_stage_progression()
                        break

            for pulse in self.pulses:
                if pulse.alive and enemy.alive and enemy.hit_by_pulse(pulse):
                    enemy.alive = False
                    self.player.reward_combo(1)
                    reward = 80 + 20 * self.player.combo
                    self.player.score += reward
                    self.add_combo_popup(f"+{reward} x{self.player.combo}", enemy.x, enemy.y)
                    self.pulse_energy = min(
                        PULSE_ENERGY_MAX, self.pulse_energy + PULSE_GAIN_ON_HIT * 0.5
                    )
                    self.kills_this_stage += 1
                    self._maybe_spawn_special(enemy.x, enemy.y)
                    self._check_stage_progression()
                    if self.score_sound:
                        self.score_sound.play()
                    break

        self.enemies = [enemy for enemy in self.enemies if enemy.alive]
        self.pulses = [pulse for pulse in self.pulses if pulse.alive]
        self.harpoons = [harpoon for harpoon in self.harpoons if harpoon.alive]
        self.special_catches = [catch for catch in self.special_catches if not catch.collected]

        for particle in self.particles:
            particle.update(dt)
        self.particles = [particle for particle in self.particles if particle.life > 0]

        if self.buoy and self.buoy.collected_by(self.player.x, self.player.y):
            self._advance_stage()

        for catch in self.special_catches:
            if catch.collected_by(self.player.x, self.player.y):
                if self.special_stock < SPECIAL_MAX_STOCK:
                    self.special_stock += 1
                if self.special_sound:
                    self.special_sound.play()
                self.add_combo_popup("Tidal Relic", self.player.x, self.player.y - 40)

        self.special_catches = [catch for catch in self.special_catches if not catch.collected]

        for popup in self.combo_popups:
            popup.update(dt)
        self.combo_popups = [popup for popup in self.combo_popups if popup.ttl > 0]

        if self.pending_special and self.special_stock > 0:
            self._trigger_special_strike()
        self.pending_special = False

        if self.player.last_combo_time > 4.0 and self.player.combo > 0:
            self.player.combo = max(0, self.player.combo - 1)
            self.player.last_combo_time = 0.0

        if self.player.health <= 0 and self.state != "game_over":
            self.state = "game_over"

        self.high_score = max(self.high_score, int(self.player.score))

    def fire_harpoon(self) -> None:
        direction = self.player.facing or 1
        start_x = self.player.x + direction * (PLAYER_RADIUS + 14)
        start_y = self.player.y - 8
        self.harpoons.append(Harpoon(start_x, start_y, direction))
        self.shoot_timer = HARPOON_COOLDOWN

    def _check_stage_progression(self) -> None:
        if self.stage >= 10:
            self.spawn_interval = max(0.45, ENEMY_SPAWN_EVERY - 0.1 * 9)
            self.kills_this_stage = min(self.kills_this_stage, self.stage_goal)
            return
        if self.awaiting_buoy:
            self.kills_this_stage = min(self.kills_this_stage, self.stage_goal)
            return
        if self.kills_this_stage >= self.stage_goal:
            self.kills_this_stage = self.stage_goal
            buoy_x = WIDTH * 0.75 + random.uniform(-40, 40)
            buoy_y = generate_wave_y(buoy_x, self.phase, self.runtime) - 30
            self.buoy = Buoy(buoy_x, buoy_y, self.player.x)
            self.awaiting_buoy = True
            self.stage_banner_timer = 3.2
            self.stage_banner_text = "Collect the signal buoy!"

    def _advance_stage(self) -> None:
        if not self.awaiting_buoy:
            return
        self.awaiting_buoy = False
        self.buoy = None
        self.stage += 1
        self.kills_this_stage = 0
        self.stage_goal = self._goal_for_stage(self.stage)
        self.stage_banner_timer = 3.2
        self.stage_banner_text = f"Stage {self.stage}: {self._stage_name(self.stage)}"
        self.spawn_interval = max(0.5, ENEMY_SPAWN_EVERY - 0.1 * (self.stage - 1))

    def _maybe_spawn_special(self, x: float, y: float) -> None:
        if len(self.special_catches) >= SPECIAL_MAX_STOCK:
            return
        if random.random() > SPECIAL_CATCH_CHANCE:
            return
        spawn_y = y - 10
        self.special_catches.append(SpecialCatch(x, spawn_y))

    def _trigger_special_strike(self) -> None:
        self.special_stock = max(0, self.special_stock - 1)
        if self.special_sound:
            self.special_sound.play()
        strike_count = 0
        for enemy in list(self.enemies):
            if not enemy.alive:
                continue
            enemy.alive = False
            strike_count += 1
            self.player.reward_combo(2)
            reward = 140 + 24 * self.player.combo
            self.player.score += reward
            self.add_combo_popup("Tidal Surge!", enemy.x, enemy.y)
            self.kills_this_stage += 1
            if strike_count >= 4:
                break
        if strike_count > 0:
            self._check_stage_progression()
            self.pulses.append(Pulse(self.player.x, self.player.y - 10))

    def draw_background(self):
        self.screen.blit(self.sky_surface, (0, 0))

    def draw_water(self):
        mesh = getattr(self, "wave_mesh", [])
        poly = [(0, HEIGHT)] + mesh + [(WIDTH, HEIGHT)]
        if len(poly) >= 3:
            water_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            pygame.draw.polygon(water_surface, WATER_BOTTOM, poly)
            gradient_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            for i in range(40):
                shade = lerp(0.25, 0.85, i / 40)
                color = (
                    int(WATER_TOP[0] * shade),
                    int(WATER_TOP[1] * shade),
                    int(WATER_TOP[2] * shade),
                    int(80 - i * 1.5),
                )
                offset_poly = [
                    (x, y + i * 3)
                    for x, y in mesh
                ]
                pygame.draw.lines(gradient_surface, color, False, offset_poly, 2)
            water_surface.blit(gradient_surface, (0, 0))

            crest = [
                (
                    x,
                    y + math.sin((x * 0.01) + self.runtime * 1.6) * 5,
                )
                for x, y in mesh
            ]
            pygame.draw.lines(water_surface, (224, 248, 255), False, crest, 3)

            foam_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            for i in range(2, len(mesh) - 2, 2):
                prev_y = mesh[i - 2][1]
                next_y = mesh[i + 2][1]
                slope = abs(next_y - prev_y)
                if slope < 14:
                    px, py = mesh[i]
                    radius = 8 + (14 - slope) * 0.8
                    pygame.draw.circle(
                        foam_surface,
                        (240, 252, 255, 160),
                        (int(px), int(py - 6)),
                        int(radius),
                    )
            water_surface.blit(foam_surface, (0, 0))

            glow_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            pygame.draw.polygon(glow_surface, (*WATER_GLOW, 80), poly)
            water_surface.blit(glow_surface, (0, 0))

            self.screen.blit(water_surface, (0, 0))

        spawner_x = WIDTH - 32
        spawner_y = generate_wave_y(WIDTH + 60, self.phase, self.runtime) - 16
        curl_surface = pygame.Surface((220, 200), pygame.SRCALPHA)
        lip_base = 96 + math.sin(self.runtime * 1.2) * 6
        lip_tip_y = lip_base - 36
        lip_tip_x = 170 + math.sin(self.runtime * 1.8) * 12
        fold_bottom = lip_base + 62
        fold_mid_x = lip_tip_x - 44

        body_color = (28, 108, 176, 235)
        trough_color = (12, 64, 128, 210)
        foam_color = (230, 250, 255, 220)

        body_points = [
            (0, 198),
            (48, 178),
            (92, 158),
            (124, lip_base + 22),
            (150, lip_base + 4),
            (fold_mid_x, lip_base + 10),
            (lip_tip_x, lip_tip_y),
            (lip_tip_x + 16, lip_tip_y + 28),
            (lip_tip_x - 10, lip_base + 44),
            (120, fold_bottom),
            (64, 200),
            (0, 200),
        ]
        pygame.draw.polygon(curl_surface, body_color, body_points)

        pocket_points = [
            (fold_mid_x - 26, lip_base + 34),
            (fold_mid_x, lip_base + 10),
            (lip_tip_x - 8, lip_base + 24),
            (lip_tip_x - 34, lip_base + 60),
            (118, fold_bottom),
            (72, 196),
        ]
        pygame.draw.polygon(curl_surface, trough_color, pocket_points)

        lip_points = [
            (fold_mid_x - 12, lip_base + 12),
            (fold_mid_x + 6, lip_base + 6),
            (lip_tip_x - 4, lip_base - 6),
            (lip_tip_x + 12, lip_tip_y + 20),
            (lip_tip_x - 18, lip_base + 32),
        ]
        pygame.draw.polygon(curl_surface, foam_color, lip_points)

        highlight_curve = [
            (fold_mid_x - 14, lip_base + 28),
            (fold_mid_x + 4, lip_base + 8),
            (lip_tip_x - 10, lip_base),
            (lip_tip_x + 8, lip_tip_y + 18),
        ]
        pygame.draw.aalines(curl_surface, (248, 255, 255, 210), False, highlight_curve)

        for i in range(5):
            wobble = math.sin(self.runtime * 2.0 + i * 0.8) * 3
            foam_pos = (
                lip_tip_x - 24 + i * 10,
                lip_base + 10 + i * 6 + wobble,
            )
            pygame.draw.circle(
                curl_surface,
                (240, 255, 255, 200 - i * 30),
                (int(foam_pos[0]), int(foam_pos[1])),
                max(2, 5 - i),
            )

        spray_surface = pygame.Surface((220, 200), pygame.SRCALPHA)
        for i in range(6):
            shade = 160 - i * 18
            band_points = [
                (lip_tip_x - 60 + i * 8, lip_base + 46 + i * 10),
                (lip_tip_x - 14, lip_base + 30 + i * 6),
                (lip_tip_x + 18, lip_base + 12 + i * 4),
                (lip_tip_x + 24, lip_tip_y + 36 + i * 14),
            ]
            pygame.draw.lines(
                spray_surface,
                (200, 244, 255, max(40, shade)),
                False,
                band_points,
                2,
            )
        curl_surface.blit(spray_surface, (0, 0))

        self.screen.blit(curl_surface, (spawner_x - 120, spawner_y - 120))

    def draw_ui(self):
        panel = pygame.Surface((WIDTH, 136), pygame.SRCALPHA)
        pygame.draw.rect(panel, UI_PANEL, (12, 10, WIDTH - 24, 116), border_radius=18)
        pygame.draw.rect(panel, (24, 52, 88), (20, 18, WIDTH - 40, 100), 2, border_radius=16)

        score_block = pygame.Rect(32, 24, 220, 36)
        pygame.draw.rect(panel, (24, 56, 92), score_block, border_radius=12)
        score_txt = self.font.render(f"Score {int(self.player.score):07d}", True, UI_TEXT)
        panel.blit(score_txt, (score_block.x + 12, score_block.y + 6))
        best_txt = self.font.render(f"Best {self.high_score:07d}", True, UI_MUTED)
        panel.blit(best_txt, (score_block.x + 12, score_block.y + 26))

        combo_block = pygame.Rect(268, 24, 180, 36)
        pygame.draw.rect(panel, (24, 62, 110), combo_block, border_radius=12)
        combo_txt = self.font.render(f"Combo ×{self.player.combo:02d}", True, UI_ACCENT)
        panel.blit(combo_txt, (combo_block.x + 12, combo_block.y + 6))
        best_combo_txt = self.font.render(
            f"Peak ×{self.player.best_combo:02d}", True, UI_MUTED
        )
        panel.blit(best_combo_txt, (combo_block.x + 12, combo_block.y + 24))

        stage_ratio = min(1.0, self.kills_this_stage / self.stage_goal)
        stage_name = self._stage_name(self.stage)
        stage_header = self.font.render(
            f"Stage {self.stage:02d} — {stage_name}", True, UI_TEXT
        )
        panel.blit(stage_header, (468, 20))
        progress_rect = pygame.Rect(468, 48, 260, 18)
        pygame.draw.rect(panel, (16, 42, 68), progress_rect, border_radius=9)
        fill_rect = progress_rect.copy()
        fill_rect.width = max(6, int(progress_rect.width * stage_ratio))
        pygame.draw.rect(panel, (96, 222, 255), fill_rect, border_radius=9)
        status = "Collect buoy" if self.awaiting_buoy else f"{self.kills_this_stage}/{self.stage_goal} catches"
        kill_txt = self.font.render(status, True, UI_MUTED)
        panel.blit(kill_txt, (progress_rect.x, progress_rect.bottom + 6))

        pulse_ratio = self.pulse_energy / PULSE_ENERGY_MAX
        pulse_rect = pygame.Rect(760, 26, 180, 16)
        pygame.draw.rect(panel, (24, 52, 88), pulse_rect, border_radius=9)
        pulse_fill = pulse_rect.copy()
        pulse_fill.width = int(pulse_rect.width * pulse_ratio)
        pygame.draw.rect(panel, (120, 236, 252), pulse_fill, border_radius=9)
        ready_txt = "Ready" if pulse_ratio >= 1.0 else f"Charging {int(pulse_ratio * 100)}%"
        pulse_label = self.font.render(f"Pulse {ready_txt}", True, UI_TEXT)
        panel.blit(pulse_label, (pulse_rect.x, pulse_rect.y - 22))

        relic_rect = pygame.Rect(960 - 180, 26, 150, 60)
        pygame.draw.rect(panel, (30, 70, 116), relic_rect, border_radius=14)
        relic_label = self.font.render("Tidal Relics", True, UI_TEXT)
        panel.blit(relic_label, (relic_rect.x + 16, relic_rect.y + 6))
        relic_txt = self.font.render(f"{self.special_stock}/{SPECIAL_MAX_STOCK}", True, UI_ACCENT)
        panel.blit(relic_txt, (relic_rect.x + 16, relic_rect.y + 30))

        heart_base_x = relic_rect.x - 140
        for i in range(self.player.health):
            heart_rect = pygame.Rect(0, 0, 20, 18)
            heart_rect.center = (heart_base_x + i * 32, 44)
            pygame.draw.polygon(
                panel,
                (255, 112, 148),
                [
                    (heart_rect.centerx, heart_rect.top),
                    (heart_rect.left, heart_rect.centery - 2),
                    (heart_rect.centerx, heart_rect.bottom),
                    (heart_rect.right, heart_rect.centery - 2),
                ],
            )

        control_txt = self.font.render(
            "Space Jump  •  Double-tap Space High Jump  •  L-Click Harpoon  •  R-Click Pulse  •  F Tidal Surge  •  P Pause",
            True,
            UI_MUTED,
        )
        panel.blit(control_txt, (32, 108))

        pygame.draw.rect(panel, (28, 58, 98), self.pause_rect, border_radius=12)
        pygame.draw.rect(panel, UI_ACCENT, self.pause_rect, 2, border_radius=12)
        pause_label = self.font.render("PAUSE" if not self.paused else "PLAY", True, UI_TEXT)
        label_rect = pause_label.get_rect(center=self.pause_rect.center)
        panel.blit(pause_label, label_rect)

        self.screen.blit(panel, (0, 0))

        if self.state == "intro":
            intro_lines = [
                "Welcome back to WaveRunner.",
                "You are the shoreline guardian – net those fishy glitches!",
                "Ride the swells, collect combos, unleash tidal pulses.",
                "Press Enter to begin or dive right in.",
            ]
            for i, line in enumerate(intro_lines):
                surf = self.font.render(line, True, UI_TEXT)
                self.screen.blit(
                    surf,
                    (WIDTH / 2 - surf.get_width() / 2, HEIGHT * 0.32 + i * 28),
                )
        elif self.state == "game_over":
            over = self.title_font.render("Game Over", True, UI_ACCENT)
            self.screen.blit(
                over,
                (WIDTH / 2 - over.get_width() / 2, HEIGHT / 2 - 48),
            )
            sub = self.font.render("Press R to restart the voyage", True, UI_TEXT)
            self.screen.blit(
                sub,
                (WIDTH / 2 - sub.get_width() / 2, HEIGHT / 2 + 4),
            )

    def draw(self):
        self.draw_background()
        self.draw_water()

        for pulse in self.pulses:
            pulse.draw(self.screen)

        for harpoon in self.harpoons:
            harpoon.draw(self.screen)

        for catch in self.special_catches:
            catch.draw(self.screen)

        for particle in self.particles:
            particle.draw(self.screen)

        if self.buoy:
            self.buoy.draw(self.screen)

        for enemy in self.enemies:
            enemy.draw(self.screen)

        self.player.draw(self.screen)
        for popup in self.combo_popups:
            popup.draw(self.screen)
        self.draw_ui()

        if self.stage_banner_timer > 0:
            overlay = pygame.Surface((WIDTH, 120), pygame.SRCALPHA)
            alpha = int(180 * min(1.0, self.stage_banner_timer / 3.2))
            banner_rect = pygame.Rect(0, 0, 440, 60)
            banner_rect.center = (WIDTH // 2, int(HEIGHT * 0.2))
            pygame.draw.rect(
                overlay,
                (12, 28, 48, alpha),
                banner_rect,
                border_radius=18,
            )
            title = self.title_font.render(self.stage_banner_text, True, UI_ACCENT)
            title_rect = title.get_rect(center=banner_rect.center)
            overlay.blit(title, title_rect)
            self.screen.blit(overlay, (0, 0))

        if self.paused and self.state == "gameplay":
            dim = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            dim.fill((8, 18, 28, 160))
            self.screen.blit(dim, (0, 0))
            paused_text = self.title_font.render("Paused", True, UI_TEXT)
            self.screen.blit(
                paused_text,
                (WIDTH / 2 - paused_text.get_width() / 2, HEIGHT / 2 - 30),
            )
            hint = self.font.render("Press P or click resume to continue", True, UI_ACCENT)
            self.screen.blit(
                hint,
                (WIDTH / 2 - hint.get_width() / 2, HEIGHT / 2 + 8),
            )

    def run(self):
        running = True
        while running:
            dt = self.clock.tick(FPS) / 1000.0
            running = self.handle_events()
            self.update(dt)
            self.draw()
            pygame.display.flip()

        pygame.quit()
        sys.exit(0)


if __name__ == "__main__":
    Game().run()

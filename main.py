import math
import random
import sys
from dataclasses import dataclass
from typing import List, Tuple

import pygame

# --- Game Config ---
WIDTH, HEIGHT = 960, 540
FPS = 60
WATERLINE = HEIGHT * 0.65
WAVE_POINTS = 120          # fidelity of the water mesh
WAVE_SPEED = 0.9           # global wave phase speed
BASE_AMPLITUDE = 38        # base wave height
AMPLITUDE_SWAY = 22        # extra amplitude that swells over time
WAVELENGTH = 240           # distance between crests

PLAYER_COLOR = (255, 245, 180)
PLAYER_RADIUS = 14
PLAYER_ACCEL = 0.55
PLAYER_FRICTION = 0.88
PLAYER_GRAVITY = 0.75
JUMP_VELOCITY = -12

ENEMY_COLOR = (255, 110, 110)
ENEMY_SPAWN_EVERY = 1.25   # seconds between enemy waves
ENEMY_MIN_SPEED = 2.4
ENEMY_MAX_SPEED = 4.6
ENEMY_RADIUS = 12

PULSE_COLOR = (120, 200, 255)
PULSE_COOLDOWN = 2.0       # seconds
PULSE_RADIUS_MAX = 220
PULSE_THICKNESS = 3

BACKGROUND = (14, 18, 28)
WATER_TOP = (24, 84, 124)
WATER_BOTTOM = (10, 40, 70)
SPRAY_COLOR = (200, 240, 255)

pygame.init()
pygame.font.init()
try:
    pygame.mixer.init()
except pygame.error:
    # Running without audio is fine when a device isn't present.
    pygame.mixer = None  # type: ignore

screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("WaveRunner – a waves-on-waves jam prototype")
clock = pygame.time.Clock()
font = pygame.font.SysFont("consolas", 20)


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


class Enemy:
    VARIANT_COLORS = {
        "standard": ENEMY_COLOR,
        "hopper": (255, 180, 110),
        "diver": (255, 70, 180),
    }

    def __init__(self, x: float, speed: float, variant: str):
        self.x = x
        self.speed = speed
        self.variant = variant
        self.alive = True
        self.t = 0.0
        self.y = WATERLINE
        self.warning = 0.4

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
        else:
            self.y = wave_y - 6

        if self.x < -40:
            self.alive = False

        if self.warning > 0:
            self.warning -= dt

    def draw(self, surf: pygame.Surface) -> None:
        color = self.VARIANT_COLORS.get(self.variant, ENEMY_COLOR)
        pygame.draw.circle(surf, color, (int(self.x), int(self.y)), ENEMY_RADIUS)
        if self.warning > 0:
            alpha = int(255 * (self.warning / 0.4))
            overlay_color = (*color, alpha)
            flash_surface = pygame.Surface((ENEMY_RADIUS * 2, ENEMY_RADIUS * 2), pygame.SRCALPHA)
            pygame.draw.circle(
                flash_surface,
                overlay_color,
                (ENEMY_RADIUS, ENEMY_RADIUS),
                ENEMY_RADIUS,
            )
            surf.blit(flash_surface, (int(self.x) - ENEMY_RADIUS, int(self.y) - ENEMY_RADIUS))

    def hit_by_pulse(self, pulse: "Pulse") -> bool:
        if not pulse.alive:
            return False
        dx = self.x - pulse.x
        dy = self.y - pulse.y
        return dx * dx + dy * dy <= (pulse.r + ENEMY_RADIUS) ** 2


class Player:
    def __init__(self):
        self.x = WIDTH * 0.25
        self.y = WATERLINE - 40
        self.vx = 0.0
        self.vy = 0.0
        self.on_water = True
        self.health = 3
        self.iframes = 0.0
        self.score = 0.0
        self.combo = 0
        self.best_combo = 0
        self.last_combo_time = 0.0

    def update(self, dt: float, keys, phase: float, t: float, particles: List[Particle]):
        ax = 0.0
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            ax -= PLAYER_ACCEL
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            ax += PLAYER_ACCEL
        self.vx += ax * 60 * dt
        self.vx *= PLAYER_FRICTION
        self.x += self.vx
        self.x = max(12, min(WIDTH - 12, self.x))

        wave_y = generate_wave_y(self.x, phase, t)
        target = wave_y - 22

        if self.on_water:
            dy = target - self.y
            self.vy += dy * 10 * dt
            if abs(self.vx) > 3 and random.random() < 0.5 * dt:
                ang = random.uniform(-0.7, 0.7)
                particles.append(
                    Particle(
                        self.x,
                        wave_y,
                        60 * math.cos(ang),
                        -60 * abs(math.sin(ang)),
                        life=0.6,
                    )
                )
        else:
            self.vy += PLAYER_GRAVITY

        if (keys[pygame.K_SPACE] or keys[pygame.K_w] or keys[pygame.K_UP]) and self.on_water:
            self.vy = JUMP_VELOCITY
            self.on_water = False

        self.y += self.vy * dt * 60

        if not self.on_water and self.y >= target:
            self.y = target
            self.vy = 0.0
            self.on_water = True
            for _ in range(6):
                ang = random.uniform(-1.2, 1.2)
                particles.append(
                    Particle(
                        self.x,
                        wave_y,
                        90 * math.cos(ang),
                        -90 * abs(math.sin(ang)),
                        life=0.9,
                    )
                )

        if self.iframes > 0:
            self.iframes -= dt

        self.score += dt * 4 * (1 + self.combo * 0.02)
        self.last_combo_time += dt

    def draw(self, surf: pygame.Surface) -> None:
        flicker = self.iframes > 0 and int(pygame.time.get_ticks() * 0.02) % 2 == 0
        color = (240, 240, 240) if not flicker else (120, 120, 120)
        pygame.draw.circle(surf, color, (int(self.x), int(self.y)), PLAYER_RADIUS)
        pygame.draw.polygon(
            surf,
            (240, 240, 240),
            [
                (self.x + 12, self.y),
                (self.x + 22, self.y - 3),
                (self.x + 22, self.y + 3),
            ],
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
        self.sky_surface = self._build_sky()
        self.combo_popups: List[ComboPopup] = []
        self.hit_sound = create_tone(220, duration=0.18, volume=0.5)
        self.pulse_sound = create_tone(660, duration=0.1, volume=0.35)
        self.score_sound = create_tone(440, duration=0.12, volume=0.4)

        self.state = "intro"
        self.state_timer = 0.0
        self.reset()

    def _build_sky(self) -> pygame.Surface:
        surf = pygame.Surface((WIDTH, HEIGHT))
        for i in range(HEIGHT):
            t = i / HEIGHT
            r = int(lerp(BACKGROUND[0], WATER_BOTTOM[0], t * 0.3))
            g = int(lerp(BACKGROUND[1], WATER_BOTTOM[1], t * 0.3))
            b = int(lerp(BACKGROUND[2], WATER_BOTTOM[2], t * 0.3))
            pygame.draw.line(surf, (r, g, b), (0, i), (WIDTH, i))
        return surf.convert()

    def reset(self):
        self.player = Player()
        self.enemies: List[Enemy] = []
        self.particles: List[Particle] = []
        self.pulses: List[Pulse] = []
        self.spawn_timer = 0.0
        self.pulse_timer = 0.0
        self.runtime = 0.0
        self.phase = 0.0
        self.combo_popups.clear()
        self.state = "intro"
        self.state_timer = 0.0

    def spawn_enemy_wave(self):
        n = random.randint(2, 4)
        spacing = random.randint(28, 48)
        start_x = WIDTH + 50
        base_speed = random.uniform(ENEMY_MIN_SPEED, ENEMY_MAX_SPEED)
        variants = ["standard", "hopper", "diver"]
        for i in range(n):
            variant = random.choices(variants, weights=[0.5, 0.25, 0.25])[0]
            enemy = Enemy(start_x + i * spacing, base_speed * random.uniform(0.9, 1.1), variant)
            self.enemies.append(enemy)

    def add_combo_popup(self, text: str, x: float, y: float):
        surf = self.font.render(text, True, (255, 245, 180))
        popup = ComboPopup(surf, pygame.Vector2(x - surf.get_width() / 2, y - 30), 0.9)
        self.combo_popups.append(popup)

    def handle_events(self) -> bool:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_r:
                    self.reset()
                elif event.key == pygame.K_RETURN and self.state == "intro":
                    self.state = "gameplay"
        return True

    def update(self, dt: float):
        self.state_timer += dt
        if self.state == "intro" and self.state_timer > 2.5:
            self.state = "gameplay"

        if self.state != "gameplay":
            return

        self.runtime += dt
        self.phase += WAVE_SPEED * dt

        keys = pygame.key.get_pressed()

        self.pulse_timer += dt
        if (keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]) and self.pulse_timer >= PULSE_COOLDOWN:
            self.pulses.append(Pulse(self.player.x, self.player.y))
            self.pulse_timer = 0.0
            if self.pulse_sound:
                self.pulse_sound.play()

        mesh = build_wave_mesh(self.phase, self.runtime)
        self.wave_mesh = mesh

        self.player.update(dt, keys, self.phase, self.runtime, self.particles)

        self.spawn_timer += dt
        if self.spawn_timer >= ENEMY_SPAWN_EVERY:
            self.spawn_timer = 0.0
            self.spawn_enemy_wave()

        for enemy in self.enemies:
            enemy.update(dt, self.phase, self.runtime)

        for pulse in self.pulses:
            pulse.update(dt)

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

            for pulse in self.pulses:
                if pulse.alive and enemy.alive and enemy.hit_by_pulse(pulse):
                    enemy.alive = False
                    self.player.reward_combo(1)
                    reward = 80 + 20 * self.player.combo
                    self.player.score += reward
                    self.add_combo_popup(f"+{reward} x{self.player.combo}", enemy.x, enemy.y)
                    if self.score_sound:
                        self.score_sound.play()
                    break

        self.enemies = [enemy for enemy in self.enemies if enemy.alive]
        self.pulses = [pulse for pulse in self.pulses if pulse.alive]

        for particle in self.particles:
            particle.update(dt)
        self.particles = [particle for particle in self.particles if particle.life > 0]

        for popup in self.combo_popups:
            popup.update(dt)
        self.combo_popups = [popup for popup in self.combo_popups if popup.ttl > 0]

        if self.player.last_combo_time > 4.0 and self.player.combo > 0:
            self.player.combo = max(0, self.player.combo - 1)
            self.player.last_combo_time = 0.0

        if self.player.health <= 0 and self.state != "game_over":
            self.state = "game_over"

    def draw_background(self):
        self.screen.blit(self.sky_surface, (0, 0))

    def draw_water(self):
        poly = [(0, HEIGHT)] + getattr(self, "wave_mesh", []) + [(WIDTH, HEIGHT)]
        if len(poly) >= 3:
            pygame.draw.polygon(self.screen, WATER_BOTTOM, poly)
            pygame.draw.lines(self.screen, WATER_TOP, False, poly[1:-1], 3)

    def draw_ui(self):
        title = self.font.render(
            "WAVERUNNER — Ride the waves. Space to jump. Shift to pulse.", True, (220, 230, 255)
        )
        self.screen.blit(title, (16, 12))

        score_txt = self.font.render(f"Score: {int(self.player.score):06d}", True, (230, 230, 230))
        self.screen.blit(score_txt, (16, 40))

        combo_txt = self.font.render(f"Combo: x{self.player.combo}", True, (200, 225, 255))
        self.screen.blit(combo_txt, (16, 64))

        best_combo_txt = self.font.render(
            f"Best Combo: x{self.player.best_combo}", True, (190, 200, 255)
        )
        self.screen.blit(best_combo_txt, (16, 88))

        cd = max(0.0, PULSE_COOLDOWN - self.pulse_timer)
        pulse_txt = self.font.render(
            f"Pulse: {'READY' if cd == 0 else f'{cd:.1f}s'}", True, (180, 255, 220)
        )
        self.screen.blit(pulse_txt, (16, 112))

        for i in range(self.player.health):
            pygame.draw.polygon(
                self.screen,
                (255, 140, 160),
                [
                    (WIDTH - 30 - i * 22, 22),
                    (WIDTH - 18 - i * 22, 10),
                    (WIDTH - 6 - i * 22, 22),
                    (WIDTH - 18 - i * 22, 34),
                ],
            )

        if self.state == "intro":
            intro_lines = [
                "Welcome to WaveRunner!",
                "Hold A/D to carve, Space to jump",
                "Shift sends a pulse that blasts foes",
                "Avoid collisions — combos break if you wipe out",
                "Press Enter to begin or just start riding",
            ]
            for i, line in enumerate(intro_lines):
                surf = self.font.render(line, True, (240, 240, 255))
                self.screen.blit(
                    surf,
                    (WIDTH / 2 - surf.get_width() / 2, HEIGHT * 0.32 + i * 26),
                )
        elif self.state == "game_over":
            over = self.font.render(
                "Game Over — press R to restart", True, (255, 220, 230)
            )
            self.screen.blit(
                over,
                (WIDTH / 2 - over.get_width() / 2, HEIGHT / 2 - 10),
            )

    def draw(self):
        self.draw_background()
        self.draw_water()

        for pulse in self.pulses:
            pulse.draw(self.screen)

        for particle in self.particles:
            particle.draw(self.screen)

        for enemy in self.enemies:
            enemy.draw(self.screen)

        self.player.draw(self.screen)
        for popup in self.combo_popups:
            popup.draw(self.screen)
        self.draw_ui()

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

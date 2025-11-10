import math
import random
import sys
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
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("WaveRunner – a waves-on-waves jam prototype")
clock = pygame.time.Clock()
font = pygame.font.SysFont("consolas", 20)

# --- Helpers ---

def lerp(a, b, t):
    return a + (b - a) * t


def generate_wave_y(x, phase, t):
    """Compute water surface Y at X using multiple sine layers."""
    # Layered sine for richer motion
    k = (2 * math.pi) / WAVELENGTH
    a = BASE_AMPLITUDE + AMPLITUDE_SWAY * (0.5 + 0.5 * math.sin(t * 0.3))
    y = WATERLINE + a * math.sin(k * x + phase)
    y += 0.33 * a * math.sin(0.5 * k * x - 0.7 * phase + t * 0.6)
    y += 0.12 * a * math.sin(1.7 * k * x + 1.9 * phase)
    return y


def build_wave_mesh(phase, t):
    pts = []
    for i in range(WAVE_POINTS + 1):
        x = i * (WIDTH / WAVE_POINTS)
        y = generate_wave_y(x, phase, t)
        pts.append((x, y))
    return pts


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life")

    def __init__(self, x, y, vx, vy, life=0.8):
        self.x, self.y, self.vx, self.vy, self.life = x, y, vx, vy, life

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += 40 * dt
        self.life -= dt

    def draw(self, surf):
        if self.life <= 0:
            return
        alpha = max(0, min(255, int(255 * (self.life / 0.8))))
        s = pygame.Surface((3, 3), pygame.SRCALPHA)
        s.fill((*SPRAY_COLOR, alpha))
        surf.blit(s, (self.x, self.y))


class Pulse:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.r = 0
        self.alive = True

    def update(self, dt):
        self.r += 320 * dt
        if self.r > PULSE_RADIUS_MAX:
            self.alive = False

    def draw(self, surf):
        if self.r > 2:
            pygame.draw.circle(surf, PULSE_COLOR, (int(self.x), int(self.y)), int(self.r), PULSE_THICKNESS)


class Enemy:
    def __init__(self, x, speed):
        self.x = x
        self.speed = speed
        self.alive = True
        self.t = 0.0

    def update(self, dt, phase, t):
        self.x -= self.speed * 60 * dt
        self.y = generate_wave_y(self.x, phase, t) - 6
        if self.x < -40:
            self.alive = False

    def draw(self, surf):
        pygame.draw.circle(surf, ENEMY_COLOR, (int(self.x), int(self.y)), ENEMY_RADIUS)

    def hit_by_pulse(self, pulse: Pulse):
        if not pulse.alive:
            return False
        dx = self.x - pulse.x
        dy = self.y - pulse.y
        return dx * dx + dy * dy <= (pulse.r + ENEMY_RADIUS) ** 2


class Player:
    def __init__(self):
        self.x = WIDTH * 0.25
        self.y = WATERLINE - 40
        self.vx = 0
        self.vy = 0
        self.on_water = True
        self.health = 3
        self.iframes = 0.0
        self.score = 0
        self.combo = 0

    def update(self, dt, keys, phase, t, particles):
        # Horizontal control
        ax = 0
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            ax -= PLAYER_ACCEL
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            ax += PLAYER_ACCEL
        self.vx += ax * 60 * dt
        self.vx *= PLAYER_FRICTION
        self.x += self.vx
        self.x = max(12, min(WIDTH - 12, self.x))

        # Vertical / surfing
        wave_y = generate_wave_y(self.x, phase, t)
        target = wave_y - 22

        if self.on_water:
            # Stick to wave with a little spring to feel floaty
            dy = target - self.y
            self.vy += dy * 10 * dt
            # Splash particles when moving fast across surface
            if abs(self.vx) > 3 and random.random() < 0.5 * dt:
                ang = random.uniform(-0.7, 0.7)
                particles.append(Particle(self.x, wave_y, 60 * math.cos(ang), -60 * abs(math.sin(ang))))
        else:
            self.vy += PLAYER_GRAVITY

        # Jump
        if (keys[pygame.K_SPACE] or keys[pygame.K_w] or keys[pygame.K_UP]) and self.on_water:
            self.vy = JUMP_VELOCITY
            self.on_water = False

        self.y += self.vy * dt * 60

        # Land back on wave if crossing it
        if not self.on_water and self.y >= target:
            self.y = target
            self.vy = 0
            self.on_water = True
            # landing splash
            for _ in range(6):
                ang = random.uniform(-1.2, 1.2)
                particles.append(Particle(self.x, wave_y, 90 * math.cos(ang), -90 * abs(math.sin(ang))))

        if self.iframes > 0:
            self.iframes -= dt

        self.score += dt * 10 * (1 + self.combo * 0.05)

    def draw(self, surf):
        flicker = (self.iframes > 0 and int(pygame.time.get_ticks() * 0.02) % 2 == 0)
        color = (240, 240, 240) if not flicker else (120, 120, 120)
        pygame.draw.circle(surf, color, (int(self.x), int(self.y)), PLAYER_RADIUS)
        # tiny fin indicating facing
        pygame.draw.polygon(surf, (240, 240, 240), [
            (self.x + 12, self.y),
            (self.x + 22, self.y - 3),
            (self.x + 22, self.y + 3),
        ])

    def damage(self):
        if self.iframes <= 0:
            self.health -= 1
            self.iframes = 1.0
            self.combo = 0


# --- Game State ---
phase = 0.0
player = Player()
enemies = []
particles = []
pulses = []
spawn_timer = 0.0
pulse_timer = 0.0
runtime = 0.0


def draw_background(surf):
    # Vertical gradient sky
    for i in range(HEIGHT):
        t = i / HEIGHT
        r = int(lerp(BACKGROUND[0], WATER_BOTTOM[0], t * 0.3))
        g = int(lerp(BACKGROUND[1], WATER_BOTTOM[1], t * 0.3))
        b = int(lerp(BACKGROUND[2], WATER_BOTTOM[2], t * 0.3))
        pygame.draw.line(surf, (r, g, b), (0, i), (WIDTH, i))


def draw_water(surf, mesh):
    # Fill under the wave
    poly = [(0, HEIGHT)] + mesh + [(WIDTH, HEIGHT)]
    pygame.draw.polygon(surf, WATER_BOTTOM, poly)

    # Crest line
    pygame.draw.lines(surf, WATER_TOP, False, mesh, 3)


def draw_ui(surf):
    title = font.render("WAVERUNNER — Ride the waves. Space to jump. Shift to pulse.", True, (220, 230, 255))
    surf.blit(title, (16, 12))

    score_txt = font.render(f"Score: {int(player.score):06d}", True, (230, 230, 230))
    surf.blit(score_txt, (16, 40))

    combo_txt = font.render(f"Combo: x{player.combo}", True, (200, 225, 255))
    surf.blit(combo_txt, (16, 64))

    cd = max(0.0, PULSE_COOLDOWN - pulse_timer)
    pulse_txt = font.render(f"Pulse: {'READY' if cd == 0 else f'{cd:.1f}s'}", True, (180, 255, 220))
    surf.blit(pulse_txt, (16, 88))

    # Hearts
    for i in range(player.health):
        pygame.draw.polygon(surf, (255, 140, 160), [
            (WIDTH - 30 - i * 22, 22),
            (WIDTH - 18 - i * 22, 10),
            (WIDTH - 6 - i * 22, 22),
            (WIDTH - 18 - i * 22, 34),
        ])


def spawn_enemy_wave():
    n = random.randint(2, 4)
    spacing = random.randint(28, 48)
    start_x = WIDTH + 50
    speed = random.uniform(ENEMY_MIN_SPEED, ENEMY_MAX_SPEED)
    for i in range(n):
        enemies.append(Enemy(start_x + i * spacing, speed))


def reset():
    global player, enemies, particles, pulses, spawn_timer, pulse_timer, runtime, phase
    player = Player()
    enemies = []
    particles = []
    pulses = []
    spawn_timer = 0.0
    pulse_timer = 0.0
    runtime = 0.0
    phase = 0.0


# --- Main Loop ---
running = True
while running:
    dt = clock.tick(FPS) / 1000.0
    runtime += dt
    phase += WAVE_SPEED * dt

    # Events
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_r:
                reset()

    keys = pygame.key.get_pressed()

    # Pulse ability (Shift)
    pulse_timer += dt
    if (keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]) and pulse_timer >= PULSE_COOLDOWN:
        pulses.append(Pulse(player.x, player.y))
        pulse_timer = 0.0

    # Build wave
    mesh = build_wave_mesh(phase, runtime)

    # Update player
    player.update(dt, keys, phase, runtime, particles)

    # Enemies
    spawn_timer += dt
    if spawn_timer >= ENEMY_SPAWN_EVERY:
        spawn_timer = 0.0
        spawn_enemy_wave()

    for e in enemies:
        e.update(dt, phase, runtime)

    # Pulses
    for p in pulses:
        p.update(dt)

    # Collisions
    for e in enemies:
        if not e.alive:
            continue
        # Player collision
        dx = e.x - player.x
        dy = e.y - player.y
        if dx * dx + dy * dy <= (ENEMY_RADIUS + PLAYER_RADIUS) ** 2:
            player.damage()
            e.alive = False
            if player.health <= 0:
                running = False
        # Pulse collision
        for p in pulses:
            if e.alive and p.alive and e.hit_by_pulse(p):
                e.alive = False
                player.combo = min(99, player.combo + 1)
                player.score += 50 * player.combo

    # Cleanup
    enemies = [e for e in enemies if e.alive]
    pulses = [p for p in pulses if p.alive]

    for pr in particles:
        pr.update(dt)
    particles = [pr for pr in particles if pr.life > 0]

    # Draw
    screen.fill(BACKGROUND)
    draw_background(screen)
    draw_water(screen, mesh)

    for p in pulses:
        p.draw(screen)

    for pr in particles:
        pr.draw(screen)

    for e in enemies:
        e.draw(screen)

    player.draw(screen)
    draw_ui(screen)

    # Game over quick screen
    if player.health <= 0:
        over = font.render("Game Over — press R to restart or close window", True, (255, 220, 230))
        screen.blit(over, (WIDTH / 2 - over.get_width() / 2, HEIGHT / 2 - 10))
        pygame.display.flip()
        # Pause loop until R or quit
        waiting = True
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)
                if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    reset()
                    waiting = False
            clock.tick(60)

    pygame.display.flip()

pygame.quit()

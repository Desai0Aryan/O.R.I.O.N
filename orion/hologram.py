"""A real-time 3D particle hologram, rendered on the CPU with numpy (no GPU or OpenGL needed).

Thousands of points live in 3D space (a sphere shell, a glowing mesh, a core, orbiting rings, a dial ring, floating
data cubes, dust, a projector base), get rotated and perspective-projected every frame, splatted into a float
buffer with additive blending, bloomed, tone-mapped and handed to Qt as one image."""
import math

import numpy as np

TAU = math.tau
BLUE = np.array([0.22, 0.52, 1.00], np.float32)
CYAN = np.array([0.30, 0.86, 1.00], np.float32)
ICE = np.array([0.80, 0.93, 1.00], np.float32)
VIOLET = np.array([0.55, 0.38, 1.00], np.float32)
WHITE = np.array([1.0, 1.0, 1.0], np.float32)
GREY = np.array([0.55, 0.60, 0.68], np.float32)

# name: (main, secondary, highlight, UI accent colour)
THEMES = {
    "arc":    (BLUE, CYAN, ICE, "#5aa8ff"),                                                    # the classic arc-reactor blue
    "ember":  ((1.00, 0.45, 0.14), (1.00, 0.70, 0.25), (1.00, 0.92, 0.78), "#ff9a4d"),         # molten orange
    "aurora": ((0.12, 0.85, 0.55), (0.35, 1.00, 0.85), (0.85, 1.00, 0.95), "#4de3a3"),         # northern-lights green
    "nebula": ((0.62, 0.34, 1.00), (0.95, 0.45, 0.95), (0.95, 0.88, 1.00), "#b58cff"),         # violet and magenta
    "crimson": ((1.00, 0.18, 0.28), (1.00, 0.45, 0.40), (1.00, 0.88, 0.88), "#ff5a6e"),        # red alert
    "ghost":  ((0.70, 0.78, 0.90), (0.85, 0.92, 1.00), (1.00, 1.00, 1.00), "#c9d6ea"),         # silver
}
THEMES = {k: (np.array(a, np.float32), np.array(b, np.float32), np.array(c, np.float32), d) for k, (a, b, c, d) in THEMES.items()}

# the constellation Orion, hand-placed (x right, y up): stars with a brightness, and the lines between them
ORION_STARS = [(-0.55, 0.95, 1.0), (0.55, 0.88, 0.8), (0.00, 1.28, 0.5),            # Betelgeuse, Bellatrix, Meissa
               (-0.28, 0.02, 0.8), (0.00, 0.12, 0.9), (0.28, 0.22, 0.8),             # the belt: Alnitak, Alnilam, Mintaka
               (-0.45, -0.95, 0.7), (0.55, -1.00, 1.0),                              # Saiph, Rigel
               (0.98, 1.04, 0.45), (1.22, 0.68, 0.45), (1.24, 0.28, 0.45), (1.08, -0.06, 0.45)]   # the shield
ORION_LINES = [(2, 0), (2, 1), (0, 3), (1, 5), (3, 4), (4, 5), (3, 6), (5, 7), (1, 8), (8, 9), (9, 10), (10, 11), (11, 5)]


def fib_sphere(n):
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = math.pi * (1 + 5 ** 0.5) * i
    return np.stack([np.cos(th) * np.sin(phi), np.cos(phi), np.sin(th) * np.sin(phi)], 1).astype(np.float32)


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], np.float32)


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], np.float32)


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], np.float32)


def unit(v):
    return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-9)


def envelope_from_samples(mono, sr, win_s=0.04):
    """Per-window loudness and bass/mid/high energy for a mono float signal -> array (N, 4), each 0..1."""
    win = max(64, int(sr * win_s))
    n = len(mono) // win
    if n <= 0:
        return None
    x = mono[:n * win].reshape(n, win).astype(np.float32)
    amp = np.sqrt((x ** 2).mean(axis=1))
    spec = np.abs(np.fft.rfft(x * np.hanning(win), axis=1))
    f = np.fft.rfftfreq(win, 1.0 / sr)
    bands = [spec[:, (f >= lo) & (f < hi)].sum(axis=1) for lo, hi in ((60, 300), (300, 2000), (2000, 7000))]
    out = np.stack([amp] + bands, 1)
    for c in range(4):
        ref = float(np.percentile(out[:, c], 95)) or 1.0
        out[:, c] = np.clip(out[:, c] / ref, 0, 1) ** 0.75
    return out


class Hologram:
    D = 6.0                     # camera distance in sphere radii

    def __init__(self, w, h, r_px, detail=1.0, seed=7):
        self.w, self.h, self.r = int(w), int(h), float(r_px)
        self.cx, self.cy = self.w / 2.0, self.h * 0.47
        self.detail = detail
        rng = np.random.default_rng(seed)
        self.rng = rng
        d = lambda n: max(8, int(n * detail))
        # ---- state
        self.t = 0.0
        self.yaw = 0.0
        self.k = {"speak": 0.0, "listen": 0.0, "think": 0.0, "mute": 0.0}
        self.b = self.m = self.hi = self.lvl = 0.0
        self.pulse = 0.0
        self.theme = "arc"
        self.main = BLUE.copy()
        self.main_t = BLUE.copy()
        self.cyan, self.ice = CYAN.copy(), ICE.copy()
        self._tint_rgb = None
        self.look = np.zeros(2, np.float32)          # where the cursor is, -1..1: he turns to look at it
        self.look_t = np.zeros(2, np.float32)
        self.energy = 1.0                            # 1 = wide awake, lower = sleepy and dim
        self.boot = 0.0                              # 0 -> 1: particles stream in and assemble
        self.shocks = []                             # expanding rings (ages)
        self._arc_t, self._arcs = 0.0, []
        self._yaw_eff = 0.0
        # ---- shell
        n = d(2600)
        self.shell = fib_sphere(n)
        self.sh_ph = rng.uniform(0, TAU, n).astype(np.float32)
        mixc = rng.random(n).astype(np.float32)[:, None]
        self.sh_mix = mixc
        # ---- wireframe globe lines (meridians + latitudes), the structure that keeps the sphere legible
        u = np.linspace(0, TAU, 120, endpoint=False, dtype=np.float32)
        lines = []
        for a in np.linspace(0, math.pi, 6, endpoint=False):
            lines.append(np.stack([np.sin(u) * math.cos(a), np.cos(u), np.sin(u) * math.sin(a)], 1))
        for yv in (-0.62, 0.0, 0.62):
            rr_ = math.sqrt(1 - yv * yv)
            lines.append(np.stack([rr_ * np.cos(u), np.full_like(u, yv), rr_ * np.sin(u)], 1))
        self.globe = np.concatenate(lines).astype(np.float32)
        self.globe_ph = np.zeros(len(self.globe), np.float32)
        # ---- mesh (nodes + geodesic edges)
        nn = d(190)
        idx = rng.choice(n, nn, replace=False)
        self.nodes = self.shell[idx]
        self.nd_ph = self.sh_ph[idx]
        dist = np.linalg.norm(self.nodes[:, None] - self.nodes[None], axis=2)
        np.fill_diagonal(dist, 9)
        near = np.argsort(dist, axis=1)[:, :2]
        pairs = {tuple(sorted((i, int(j)))) for i in range(nn) for j in near[i]}
        self.edges = np.array(sorted(pairs), np.int32)
        self.e_ph = rng.random(len(self.edges)).astype(np.float32)
        self.e_u = np.linspace(0, 1, 7, dtype=np.float32)
        # ---- core
        nc = d(320)
        v = unit(rng.normal(size=(nc, 3))).astype(np.float32)
        self.core = v * (rng.random((nc, 1)) ** 0.6).astype(np.float32) * 0.42
        self.core_ph = rng.uniform(0, TAU, nc).astype(np.float32)
        # ---- orbital rings (radius, tilt_x, tilt_z, speed, points)
        self.ring_def = [(1.62, 0.35, 0.10, 0.50), (1.98, -0.60, 0.45, -0.38), (2.36, 1.05, -0.30, 0.27)]
        self.ring_n = d(300)
        self.ring_a = (np.arange(self.ring_n) / self.ring_n * TAU).astype(np.float32)
        self.ring_rot = [0.0, 1.7, 3.4]
        # ---- dial ring (gauge ticks)
        self.tick_n = d(120)
        # ---- dust
        nd = d(170)
        self.dust_r = rng.uniform(2.0, 3.1, nd).astype(np.float32)
        self.dust_th = rng.uniform(0, TAU, nd).astype(np.float32)
        self.dust_y = rng.uniform(-1, 1, nd).astype(np.float32)
        self.dust_w = rng.uniform(0.05, 0.35, nd).astype(np.float32) * rng.choice([-1, 1], nd)
        self.dust_ph = rng.uniform(0, TAU, nd).astype(np.float32)
        # ---- data cubes
        nb = d(8)
        self.cube_c = rng.uniform(1.75, 2.7, nb).astype(np.float32)
        self.cube_th = rng.uniform(0, TAU, nb).astype(np.float32)
        self.cube_y = rng.uniform(-1.9, 1.9, nb).astype(np.float32)
        self.cube_w = rng.uniform(0.06, 0.22, nb).astype(np.float32) * rng.choice([-1, 1], nb)
        self.cube_s = rng.uniform(0.08, 0.16, nb).astype(np.float32)
        self.cube_ph = rng.uniform(0, TAU, nb).astype(np.float32)
        corners = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], np.float32)
        ce = []
        for i in range(8):
            for j in range(i + 1, 8):
                if np.abs(corners[i] - corners[j]).sum() == 2:
                    ce.append((i, j))
        self.cube_corners, self.cube_edges = corners, np.array(ce)
        # ---- spikes
        ns = d(110)
        self.spike_dirs = fib_sphere(ns * 3)[rng.choice(ns * 3, ns, replace=False)]
        self.sp_ph = rng.uniform(0, TAU, ns).astype(np.float32)
        self.sp_s = np.linspace(0, 1, 16, dtype=np.float32)
        # ---- voxel lattice: crisp pixels snapped to a 3D grid, pulsing outward from the core
        g = np.arange(-1.6, 1.61, 0.16, dtype=np.float32)
        grid = np.stack(np.meshgrid(g, g, g, indexing="ij"), -1).reshape(-1, 3)
        rr = np.linalg.norm(grid, axis=1)
        grid = grid[(rr > 1.18) & (rr < 1.62)]
        self.vox = grid[rng.choice(len(grid), min(len(grid), d(300)), replace=False)]
        self.vox_r = np.linalg.norm(self.vox, axis=1)
        self.vox_ph = rng.uniform(0, TAU, len(self.vox)).astype(np.float32)
        self.pixel = 2 if self.r > 40 else 1
        # ---- base + beam
        self.base_y = -2.55
        self.bp_n = d(100)
        nbm = d(90)
        self.beam_x = rng.uniform(-1, 1, nbm).astype(np.float32)
        self.beam_z = rng.uniform(-1, 1, nbm).astype(np.float32)
        self.beam_h = rng.random(nbm).astype(np.float32)
        self.beam_v = rng.uniform(0.12, 0.35, nbm).astype(np.float32)
        # ---- constellation, audio ring, boot scatter
        self.cs = np.array(ORION_STARS, np.float32)
        self.eq_n = d(72)
        self.eq_ph = rng.uniform(0, TAU, self.eq_n).astype(np.float32)
        self._scatter = None
        self._delay = None
        # ---- buffers
        self.acc = np.zeros((3, self.h, self.w), np.float64)
        self.out = np.zeros((self.h, self.w, 4), np.uint8)
        self.out[..., 3] = 0

    # ------------------------------------------------------------------ control
    def set_theme(self, name):
        if name not in THEMES:
            return
        self.theme = name
        self.cyan, self.ice = THEMES[name][1], THEMES[name][2]
        self.set_tint(self._tint_rgb)

    def set_tint(self, rgb):
        """Mood colour: the theme's colour, nudged a little toward how he feels."""
        self._tint_rgb = rgb
        base = THEMES[self.theme][0]
        self.main_t = (base if rgb is None else base * 0.7 + np.asarray(rgb, np.float32) * 0.3).astype(np.float32)

    def set_look(self, x, y):
        self.look_t[:] = (max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y)))

    def shockwave(self, n=1):
        self.shocks += [-0.18 * i for i in range(n)]

    def reboot(self):
        self.boot = 0.0

    def update(self, dt, state, level, bands=None, pulse=0.0):
        dt = min(0.1, max(0.0, dt))
        target = {"speak": state == "speaking", "listen": state == "listening", "think": state == "thinking",
                  "mute": state == "muted"}
        ease = 1 - math.exp(-dt * 5.0)
        for key, on in target.items():
            self.k[key] += ((1.0 if on else 0.0) - self.k[key]) * ease
        mute = self.k["mute"]
        self.t += dt * (1.0 - 0.75 * mute) * (0.8 + 0.2 * self.energy)
        self.boot = min(1.0, self.boot + dt / 2.4)
        self.look += (self.look_t - self.look) * (1 - math.exp(-dt * 4.0))
        self.shocks = [a + dt * 0.55 for a in self.shocks if a < 1.0]
        t = self.t
        if bands is None:
            tb, tm, th = level, level * (0.55 + 0.45 * abs(math.sin(t * 7.1))), level * abs(math.sin(t * 13.3 + 1.0)) * 0.8
        else:
            tb, tm, th = bands
        for name, tgt in (("b", tb), ("m", tm), ("hi", th)):
            cur = getattr(self, name)
            setattr(self, name, cur + (tgt - cur) * (1 - math.exp(-dt * (32.0 if tgt > cur else 7.0))))
        self.lvl += (level - self.lvl) * (1 - math.exp(-dt * (30.0 if level > self.lvl else 6.0)))
        self.pulse = max(self.pulse * math.exp(-dt * 4.0), pulse)
        k = self.k
        self.yaw += dt * (0.22 + 0.40 * k["think"] + 0.55 * k["speak"] * self.b + 0.10 * k["listen"]) * (1 - 0.75 * mute)
        self.main += (self.main_t - self.main) * ease * 0.5
        for i, (_, _, _, sp) in enumerate(self.ring_def):
            self.ring_rot[i] += dt * sp * (1.0 + 3.2 * k["think"] + 0.9 * k["speak"] + 0.3 * k["listen"]) * (1 - 0.8 * mute)
        # dust: drifts, streams inward while listening, is pushed out by bass while speaking
        self.dust_th += dt * self.dust_w * (1 + 2 * k["think"]) * (1 - 0.8 * mute)
        self.dust_r += dt * (-1.1 * k["listen"] + 0.9 * k["speak"] * self.b) * (1 - mute)
        self.dust_r = np.where(self.dust_r < 1.55, 3.4, np.where(self.dust_r > 3.7, 1.75, self.dust_r))
        self.beam_h += dt * self.beam_v * (1 + 2 * self.lvl)
        self.beam_h = np.where(self.beam_h > 1, self.beam_h - 1, self.beam_h)
        self.cube_th += dt * self.cube_w * (1 - 0.8 * mute)

    # ------------------------------------------------------------------ geometry
    def _radius(self, d, ph):
        t, k, b, m = self.t, self.k, self.b, self.m
        f = (np.sin(3.1 * d[:, 0] + 1.3 * t) + np.sin(3.4 * d[:, 1] - 1.7 * t) + np.sin(2.7 * d[:, 2] + 1.1 * t)) / 3
        r = 1 + 0.035 * f + 0.03 * math.sin(1.5 * t) + 0.04 * self.pulse
        r = r + k["speak"] * (b * 0.11 * (0.5 + 0.5 * f) + m * 0.04 * np.sin(t * 7 + ph))
        r = r - k["listen"] * (0.08 - 0.04 * np.sin(t * 4 - 3 * d[:, 1]) + 0.05 * self.lvl)
        r = r + k["think"] * 0.03 * np.sin(t * 9 + 6 * d[:, 1])
        return r.astype(np.float32)

    def _ring_pts(self, i):
        rad, tx, tz, _ = self.ring_def[i]
        t, k = self.t, self.k
        a = self.ring_a + self.ring_rot[i]
        rr = rad * (1 + 0.07 * k["speak"] * self.b * np.sin(a * 3 + t * 5) - 0.10 * k["listen"] + 0.02 * math.sin(t + i))
        p = np.stack([rr * np.cos(a), np.zeros_like(a), rr * np.sin(a)], 1).astype(np.float32)
        M = rot_z(tz + 0.08 * math.sin(t * 0.3 + i)) @ rot_x(tx + 0.06 * math.sin(t * 0.23 + 2 * i))
        head = (self.ring_rot[i] * 0.9 / TAU) % 1.0
        u = ((np.arange(self.ring_n) / self.ring_n) - head) % 1.0
        sign = 1.0 if self.ring_def[i][3] > 0 else -1.0
        u = u if sign > 0 else 1 - u
        inten = 0.10 + 0.9 * (1 - u) ** 3
        return p @ M.T, inten.astype(np.float32)

    def _build(self):
        """-> (positions (N,3), light (N,3)) for every particle group."""
        t, k = self.t, self.k
        b, m, hi = self.b, self.m, self.hi
        main, mute = self.main, k["mute"]
        CYAN, ICE = self.cyan, self.ice
        P, L, C = [], [], []
        Rb = rot_y(self._yaw_eff)                          # cancels the spin: things that always face you
        bill = lambda p: p @ Rb

        def add(p, col, inten, crisp=False):
            inten = np.asarray(inten, np.float32).reshape(-1)
            if inten.size == 1 and len(p) > 1:
                inten = np.full(len(p), inten[0], np.float32)
            P.append(p.astype(np.float32))
            L.append(np.asarray(col, np.float32) * inten.reshape(-1, 1))
            C.append(np.full(len(p), crisp, bool))

        ys = math.sin(t * 2.0)
        yp = 1.1 - ((t * 0.16) % 1.0) * 2.4                                         # a slow "ping" down the sphere

        # shell
        r = self._radius(self.shell, self.sh_ph)
        y = self.shell[:, 1]
        scan = np.exp(-((y - ys) ** 2) / 0.03) * k["think"] * 1.1
        ping = np.exp(-((y - yp) ** 2) / 0.02) * 0.55
        tw = 0.5 + 0.5 * np.sin(t * 2.0 + self.sh_ph)
        spark = (np.sin(t * 19 + self.sh_ph * 13.7) > 0.985).astype(np.float32) * (0.5 + 1.2 * hi * k["speak"])
        nz = (self.shell @ self._G.T)[:, 2]
        rim = (1 - np.abs(nz)) ** 2
        inten = (0.20 + 0.20 * tw + scan + ping + spark + 0.25 * self.lvl * k["listen"]) * (0.55 + 1.25 * rim)
        col = main * (1 - self.sh_mix * 0.5) + CYAN * (self.sh_mix * 0.5)
        add(self.shell * r[:, None], col, inten)

        # globe lines
        gr = self._radius(self.globe, self.globe_ph) * 1.004
        gz = (self.globe @ self._G.T)[:, 2]
        add(self.globe * gr[:, None], CYAN * 0.55 + main * 0.45, 0.20 * (0.55 + 1.2 * (1 - np.abs(gz)) ** 2) * (1 + 0.8 * self.lvl * k["speak"]))

        # mesh: nodes and edges that carry little data packets
        rn = self._radius(self.nodes, self.nd_ph)
        npos = self.nodes * rn[:, None]
        add(npos, ICE, 0.55 + 0.4 * np.sin(t * 3 + self.nd_ph) ** 2 + 0.5 * self.lvl * k["listen"], crisp=True)
        a, bq = self.edges[:, 0], self.edges[:, 1]
        u = self.e_u[None, :, None]
        seg = (1 - u) * npos[a][:, None, :] + u * npos[bq][:, None, :]
        seg = unit(seg) * ((1 - u) * rn[a][:, None, None] + u * rn[bq][:, None, None])
        head = (t * (0.55 + 0.9 * k["think"] + 0.5 * k["speak"]) + self.e_ph) % 1.0
        pk = np.exp(-((self.e_u[None, :] - head[:, None]) ** 2) / 0.015) * (0.5 + 1.6 * k["think"] + 0.9 * k["speak"] * (0.4 + b))
        add(seg.reshape(-1, 3), CYAN, (0.16 + pk).reshape(-1))

        # core
        cr = 0.92 + 0.12 * np.sin(t * 3 + self.core_ph) + 0.35 * b * k["speak"] + 0.2 * self.pulse - 0.1 * k["listen"]
        add(self.core * cr[:, None], WHITE * 0.55 + main * 0.45, 0.30 + 0.35 * b * k["speak"])

        # orbital rings
        for i in range(3):
            p, inten = self._ring_pts(i)
            col = np.where((inten > 0.6)[:, None], ICE[None], (main * 0.6 + CYAN * 0.4)[None])
            add(p, col, inten * (1.15 + 0.6 * k["speak"] * b))

        # dial ring: tick marks like a gauge
        a = (np.arange(self.tick_n) / self.tick_n * TAU + self.t * -0.12).astype(np.float32)
        longt = (np.arange(self.tick_n) % 6 == 0)
        Rr = 1.36 + 0.03 * k["speak"] * b
        Mdial = rot_x(1.35) @ rot_z(0.18)
        inner = np.stack([Rr * np.cos(a), np.zeros_like(a), Rr * np.sin(a)], 1)
        outer = np.stack([(Rr + np.where(longt, 0.10, 0.045)) * np.cos(a), np.zeros_like(a),
                          (Rr + np.where(longt, 0.10, 0.045)) * np.sin(a)], 1)
        add(inner @ Mdial.T, ICE, np.where(longt, 0.8, 0.35))
        add(outer @ Mdial.T, CYAN, np.where(longt, 0.9, 0.3))

        # spikes (the part that bursts out when he speaks)
        sd = self.spike_dirs
        n1 = 0.5 + 0.5 * np.sin(t * 5.3 + self.sp_ph * 3.1)
        n2 = 0.5 + 0.5 * np.sin(t * 9.0 + self.sp_ph)
        amp = k["speak"] * (b * 1.2 * (0.10 + 0.90 * n1 ** 2.0) + m * 0.45 * n2 ** 2) + k["think"] * 0.12 * n2 \
            + k["listen"] * 0.10 * self.lvl * n1
        Ls = 0.05 + 2.6 * np.clip(amp, 0, 1.3)
        rs = self._radius(sd, self.sp_ph) + 0.02
        s = self.sp_s[None, :]
        rad = rs[:, None] + Ls[:, None] * s ** 0.9
        pos = sd[:, None, :] * rad[:, :, None]
        inten = (0.10 + 1.6 * np.clip(amp, 0, 1.2))[:, None] * (0.55 + 0.45 * s)
        add(pos.reshape(-1, 3), ICE, inten.reshape(-1))
        tip = sd * (rs + Ls)[:, None]
        add(tip, WHITE, 0.15 + 0.95 * np.clip(amp, 0, 1.2), crisp=True)

        # voxel lattice: waves of light roll outward through it (faster and stronger when he speaks)
        front = (t * (0.55 + 0.9 * k["speak"] * (0.3 + b) + 0.5 * k["think"]) + self.vox_ph * 0.15) % 1.0
        wave = np.exp(-((self.vox_r - (1.18 + 0.45 * front)) ** 2) / 0.012)
        flick = (np.sin(t * 6 + self.vox_ph * 5) > 0.2).astype(np.float32)
        vi = flick * (0.03 + wave * (0.8 + 1.1 * k["speak"] * b + 0.6 * k["think"]))
        add(self.vox * (1 + 0.5 * k["speak"] * b * 0.3), CYAN * 0.5 + ICE * 0.5, vi, crisp=True)

        # dust
        dr = self.dust_r
        add(np.stack([dr * np.cos(self.dust_th), self.dust_y * dr * 0.55, dr * np.sin(self.dust_th)], 1),
            ICE * 0.8 + main * 0.2, 0.10 + 0.22 * (0.5 + 0.5 * np.sin(t * 2.5 + self.dust_ph)), crisp=True)

        # data cubes (little rotating wireframes)
        cp = np.stack([self.cube_c * np.cos(self.cube_th), self.cube_y + 0.15 * np.sin(t * 0.7 + self.cube_ph),
                       self.cube_c * np.sin(self.cube_th)], 1)
        on = (np.sin(t * 1.3 + self.cube_ph * 3) > -0.55).astype(np.float32)
        ce = self.cube_edges
        for j in range(len(cp)):
            M = rot_y(t * 0.9 + self.cube_ph[j]) @ rot_x(t * 0.6 + self.cube_ph[j] * 2)
            c3 = (self.cube_corners * self.cube_s[j]) @ M.T + cp[j]
            ua = np.linspace(0, 1, 6, dtype=np.float32)[None, :, None]
            segs = (1 - ua) * c3[ce[:, 0]][:, None, :] + ua * c3[ce[:, 1]][:, None, :]
            add(segs.reshape(-1, 3), CYAN * 0.6 + ICE * 0.4, np.full(segs.shape[0] * 6, 0.75 * on[j]))
            add(cp[j][None], WHITE, [1.0 * on[j]], crisp=True)

        # projector base: dashed rings + ripples + rising beam
        by = self.base_y
        for rr_, base_i in ((1.0, 0.9), (1.55, 0.6), (2.1, 0.4)):
            a = np.linspace(0, TAU, self.bp_n, endpoint=False).astype(np.float32)
            dash = 0.55 + 0.45 * (np.sin(a * 14 + t * (1.5 if rr_ != 1.55 else -1.5)) > 0)
            add(np.stack([rr_ * np.cos(a), np.full_like(a, by), rr_ * np.sin(a)], 1), ICE if rr_ == 1.0 else main,
                base_i * dash * (0.8 + 0.5 * self.lvl))
        for kk in range(3):
            ph = (t * 0.5 + kk / 3) % 1.0
            a = np.linspace(0, TAU, self.bp_n, endpoint=False).astype(np.float32)
            rr_ = (0.5 + ph * 2.5) * (1 - 0.4 * k["listen"] * ph) if k["listen"] < 0.5 else (3.0 - ph * 2.5)
            add(np.stack([rr_ * np.cos(a), np.full_like(a, by), rr_ * np.sin(a)], 1), CYAN,
                (1 - ph) * (0.25 + 0.9 * self.lvl))
        hh = self.beam_h
        wr = 0.5 * (1 - hh * 0.6)
        add(np.stack([self.beam_x * wr, by - hh * (by - 0.2), self.beam_z * wr], 1), CYAN * 0.7 + ICE * 0.3,
            np.sin(hh * math.pi) * 0.7)

        # circular audio visualiser that always faces you: his voice (or yours) drawn as a ring of bars
        n = self.eq_n
        ang = np.arange(n) / n * TAU
        sym = np.abs(np.sin(ang * 0.5))                    # mirrored left and right, like a real spectrum
        band = b * (1 - sym) ** 1.5 + m * np.sin(sym * math.pi) + hi * sym ** 1.5
        flick = 0.55 + 0.45 * np.sin(t * 11 + self.eq_ph * 3)
        amp = (k["speak"] * band * flick + k["listen"] * self.lvl * (0.6 + 0.4 * flick) * 0.9).astype(np.float32)
        rin = 1.62
        seg = np.linspace(0, 1, 5, dtype=np.float32)[None, :]
        rad = rin + (0.04 + 0.55 * np.clip(amp, 0, 1.2))[:, None] * seg
        pts = np.stack([rad * np.cos(ang)[:, None], rad * np.sin(ang)[:, None], np.full_like(rad, 0.0)], -1)
        add(bill(pts.reshape(-1, 3)), ICE * 0.6 + main * 0.4, (0.10 + 1.1 * np.clip(amp, 0, 1.2)[:, None] * (0.4 + 0.6 * seg)).reshape(-1))
        add(bill(pts[:, -1]), WHITE, 0.10 + 0.9 * np.clip(amp, 0, 1.2), crisp=True)
        aa = np.linspace(0, TAU, 160, endpoint=False).astype(np.float32)
        add(bill(np.stack([rin * np.cos(aa), rin * np.sin(aa), np.zeros_like(aa)], 1)), CYAN, 0.09 + 0.10 * (k["speak"] + k["listen"]))

        # the constellation Orion floats behind him; its belt stars become a thinking indicator
        cs = self.cs
        sc = 2.45
        dim = 4.2                                            # the chart is far behind, so depth fading would hide it
        stars = np.stack([cs[:, 0] * sc, cs[:, 1] * sc, np.full(len(cs), -2.0, np.float32)], 1)
        twk = 0.65 + 0.35 * np.sin(t * 1.3 + np.arange(len(cs)) * 1.9)
        chase = np.zeros(len(cs), np.float32)
        for j, si in enumerate((3, 4, 5)):                  # Alnitak -> Alnilam -> Mintaka, over and over
            chase[si] = k["think"] * max(0.0, math.sin(t * 5.0 - j * 1.2)) ** 2
        sbright = cs[:, 2] * twk * (0.95 + 0.5 * (k["speak"] * b + k["listen"] * self.lvl)) + chase * 1.6
        for _ in range(8):                                   # several stacked points = a soft, bright star
            add(bill(stars), ICE, sbright * 0.55 * dim)
        add(bill(stars), WHITE, sbright * dim, crisp=True)
        ua = np.linspace(0, 1, 12, dtype=np.float32)[None, :, None]
        ls = ORION_LINES
        a_i, b_i = [x for x, _ in ls], [y for _, y in ls]
        lp = (1 - ua) * stars[a_i][:, None, :] + ua * stars[b_i][:, None, :]
        add(bill(lp.reshape(-1, 3)), CYAN * 0.7 + main * 0.3, dim * (0.13 + 0.10 * k["speak"] * (0.3 + b) + 0.09 * k["think"]))

        # lightning between points of the shell while he thinks
        if k["think"] > 0.03:
            if t - self._arc_t > 0.09 or not self._arcs:
                self._arc_t = t
                self._arcs = self._make_arcs(4)
            arcs = np.concatenate(self._arcs)
            fl = 0.5 + 0.5 * np.sin(t * 40)
            add(arcs, ICE, k["think"] * (0.55 + 0.9 * fl))
        else:
            self._arcs = []

        # shockwaves: rings that roll outward when you speak to him or a reminder fires
        for age in self.shocks:
            if age <= 0:
                continue
            rr_ = 1.1 + age * 2.6
            aa = np.linspace(0, TAU, 110, endpoint=False).astype(np.float32)
            ring = np.stack([rr_ * np.cos(aa), rr_ * np.sin(aa), np.zeros_like(aa)], 1)
            add(bill(ring), ICE, 1.2 * (1 - age) ** 1.5)
        return np.concatenate(P), np.concatenate(L), np.concatenate(C)

    def _make_arcs(self, count):
        rng, out = self.rng, []
        for _ in range(count):
            a = unit(rng.normal(size=3)).astype(np.float32)
            bq = unit(a + rng.normal(size=3) * 0.9).astype(np.float32)
            pts = np.array([a, bq], np.float32)
            for jit in (0.35, 0.18, 0.09, 0.05):             # midpoint displacement = jagged bolts
                mids = unit((pts[:-1] + pts[1:]) / 2 + rng.normal(size=(len(pts) - 1, 3)) * jit)
                new = np.empty((len(pts) + len(mids), 3), np.float32)
                new[0::2], new[1::2] = pts, mids
                pts = new
            # densify the bolt so it reads as a continuous line
            ua = np.linspace(0, 1, 3, dtype=np.float32)[None, :, None]
            seg = ((1 - ua) * pts[:-1][:, None, :] + ua * pts[1:][:, None, :]).reshape(-1, 3)
            out.append((unit(seg) * 1.02).astype(np.float32))
        return out

    # ------------------------------------------------------------------ rendering
    def _splat(self, x, y, light):
        W, H = self.w, self.h
        x0 = np.floor(x).astype(np.int32)
        y0 = np.floor(y).astype(np.int32)
        fx, fy = (x - x0).astype(np.float32), (y - y0).astype(np.float32)
        for dx, dy, wgt in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
            xi, yi = x0 + dx, y0 + dy
            ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
            idx = yi[ok] * W + xi[ok]
            wv = wgt[ok]
            for c in range(3):
                self.acc[c].reshape(-1)[:] += np.bincount(idx, weights=light[ok, c] * wv, minlength=W * H)

    def _pixels(self, x, y, light):
        """Hard-edged square pixels (no smoothing), 1 or 2 px wide: the 'digital voxel' look."""
        W, H, n = self.w, self.h, self.pixel
        xi0 = np.round(x - (n - 1) / 2).astype(np.int32)
        yi0 = np.round(y - (n - 1) / 2).astype(np.int32)
        for dx in range(n):
            for dy in range(n):
                xi, yi = xi0 + dx, yi0 + dy
                ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
                idx = yi[ok] * W + xi[ok]
                for c in range(3):
                    self.acc[c].reshape(-1)[:] += np.bincount(idx, weights=light[ok, c], minlength=W * H)

    def _gauss(self, cx, cy, sigma, inten, col):
        W, H = self.w, self.h
        rad = int(sigma * 3)
        x0, x1 = max(0, int(cx) - rad), min(W, int(cx) + rad + 1)
        y0, y1 = max(0, int(cy) - rad), min(H, int(cy) + rad + 1)
        if x1 <= x0 or y1 <= y0:
            return
        xs = np.arange(x0, x1, dtype=np.float32)[None, :]
        ys = np.arange(y0, y1, dtype=np.float32)[:, None]
        g = np.exp(-((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * sigma * sigma)) * inten
        for c in range(3):
            self.acc[c, y0:y1, x0:x1] += g * col[c]

    @staticmethod
    def _blur(a):
        p = np.pad(a, ((0, 0), (2, 2), (2, 2)), mode="edge")
        p = (p[:, :, :-4] + 4 * p[:, :, 1:-3] + 6 * p[:, :, 2:-2] + 4 * p[:, :, 3:-1] + p[:, :, 4:]) / 16
        return (p[:, :-4] + 4 * p[:, 1:-3] + 6 * p[:, 2:-2] + 4 * p[:, 3:-1] + p[:, 4:]) / 16

    def _bloom(self, a):
        C, H, W = a.shape
        h2, w2 = H // 2, W // 2
        d2 = (a[:, 0:h2 * 2:2, 0:w2 * 2:2] + a[:, 1:h2 * 2:2, 0:w2 * 2:2] + a[:, 0:h2 * 2:2, 1:w2 * 2:2]
              + a[:, 1:h2 * 2:2, 1:w2 * 2:2]) * 0.25
        b2 = self._blur(d2)
        h4, w4 = h2 // 2, w2 // 2
        d4 = (b2[:, 0:h4 * 2:2, 0:w4 * 2:2] + b2[:, 1:h4 * 2:2, 0:w4 * 2:2] + b2[:, 0:h4 * 2:2, 1:w4 * 2:2]
              + b2[:, 1:h4 * 2:2, 1:w4 * 2:2]) * 0.25
        b4 = self._blur(self._blur(d4))
        up2 = np.repeat(np.repeat(b2, 2, 1), 2, 2)
        up4 = np.repeat(np.repeat(b4, 4, 1), 4, 2)
        out = np.zeros_like(a)
        out[:, :up2.shape[1], :up2.shape[2]] += up2[:, :H, :W] * 0.75
        out[:, :up4.shape[1], :up4.shape[2]] += up4[:, :H, :W] * 0.55
        return out

    def _window(self):
        if getattr(self, "_win", None) is None:
            fx = np.minimum(np.arange(self.w), np.arange(self.w)[::-1]) / (0.10 * self.w)
            fy = np.minimum(np.arange(self.h), np.arange(self.h)[::-1]) / (0.08 * self.h)
            fx, fy = np.clip(fx, 0, 1), np.clip(fy, 0, 1)
            sm = lambda v: v * v * (3 - 2 * v)
            self._win = (sm(fy)[:, None] * sm(fx)[None, :]).astype(np.float32)
        return self._win

    def render(self):
        k, mute = self.k, self.k["mute"]
        self.acc[:] = 0
        self._yaw_eff = self.yaw + float(self.look[0]) * 0.55
        G = rot_x(0.30 - float(self.look[1]) * 0.30) @ rot_y(self._yaw_eff)
        self._G = G
        pos, light, crisp = self._build()
        if self.boot < 1.0:                                  # particles streaming in from the dark and snapping into place
            n = len(pos)
            if self._scatter is None or len(self._scatter) != n:
                rr = self.rng
                self._scatter = (unit(rr.normal(size=(n, 3))) * rr.uniform(2.5, 5.5, (n, 1))).astype(np.float32)
                self._delay = rr.uniform(0, 0.55, n).astype(np.float32)
            e = np.clip((self.boot * 1.55 - self._delay) / 0.45, 0, 1)
            e = (e * e * (3 - 2 * e))[:, None]
            pos = pos * e + self._scatter * (1 - e)
            light = light * (0.15 + 0.85 * e)
        q = pos @ G.T
        z = q[:, 2]
        s = self.D / (self.D - z)
        x = self.cx + q[:, 0] * self.r * s
        y = self.cy - q[:, 1] * self.r * s
        df = np.clip(0.62 + 0.20 * z, 0.18, 1.25)[:, None]
        gain = (1.0 - 0.55 * mute) * (0.72 + 0.28 * self.energy)
        light = light * df * gain
        if mute > 0.01:
            gray = light.mean(axis=1, keepdims=True) * GREY[None]
            light = light * (1 - mute) + gray * mute
        light = light.astype(np.float32)
        soft = ~crisp
        self._splat(x[soft], y[soft], light[soft])
        self._pixels(x[crisp], y[crisp], light[crisp])
        sig = self.r * (0.50 + 0.25 * self.b * k["speak"] + 0.10 * self.pulse)
        corecol = WHITE * 0.55 + self.main * 0.45
        self._gauss(self.cx, self.cy, sig, (0.20 + 0.40 * self.b * k["speak"] + 0.18 * self.pulse + 0.10 * k["think"]) * gain, corecol)
        self._gauss(self.cx, self.cy, self.r * 1.5, 0.035 + 0.05 * self.lvl, self.main)
        # tiny bright star at the very centre
        self._gauss(self.cx, self.cy, self.r * 0.10, 0.9 * gain, WHITE)

        a = self.acc.astype(np.float32)
        lin = a + self._bloom(a) * 0.9
        col = 1.0 - np.exp(-lin * 1.2)
        alpha = np.clip((col.max(axis=0) - 0.02) / 0.98, 0, 1)
        alpha *= self._window()
        o = self.out
        o[..., 0] = col[2] * 255
        o[..., 1] = col[1] * 255
        o[..., 2] = col[0] * 255
        o[..., 3] = alpha * 255
        return o

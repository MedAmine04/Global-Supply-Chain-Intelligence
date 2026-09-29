"""Générateur d'images synthétiques de colis (Phase 5 — Computer Vision).

Les vrais datasets d'images de colis abîmés (Parcel3D/Zenodo, Roboflow
Universe, Hugging Face) sont hébergés sur des domaines inaccessibles
depuis l'environnement de développement (cf. ADR-011). Ce générateur
produit des images plausibles avec OpenCV pour pouvoir entraîner et
tester un vrai CNN ; le chargeur `load_image_folder` permet de le
remplacer par des photos réelles sans changer le reste du pipeline.

Les colis "normaux" contiennent des distracteurs bénins (ombre, pli
discret, autocollant) et une partie des dommages est subtile, pour que
la tâche ne soit pas triviale.
"""

import cv2
import numpy as np

IMAGE_SIZE = 64
DAMAGE_TYPES = ("dent", "tear", "stain", "crushed_corner")


def _box_polygon(rng: np.random.Generator, size: int) -> np.ndarray:
    w = rng.uniform(0.45, 0.72) * size
    h = rng.uniform(0.40, 0.65) * size
    cx = size / 2 + rng.uniform(-3, 3)
    cy = size / 2 + rng.uniform(-3, 3)
    angle = np.deg2rad(rng.uniform(-14, 14))
    corners = np.array([[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]])
    rot = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    return (corners @ rot.T + [cx, cy]).astype(np.int32)


def _blend(img: np.ndarray, mask: np.ndarray, color, alpha: float) -> None:
    """Mélange `color` dans `img` là où `mask` (0..1, flou) est non nul."""
    m = (cv2.GaussianBlur(mask, (5, 5), 0)[..., None] * alpha).astype(np.float32)
    img[:] = (img * (1 - m) + np.array(color, dtype=np.float32) * m).astype(np.uint8)


def _apply_damage(img, poly, rng, kind: str, severity: float) -> None:
    size = img.shape[0]
    cx, cy = poly.mean(axis=0)
    mask = np.zeros((size, size), np.float32)
    if kind == "dent":
        axes = (int(rng.uniform(5, 11)), int(rng.uniform(4, 9)))
        ox, oy = rng.uniform(-8, 8, 2)
        cv2.ellipse(mask, (int(cx + ox), int(cy + oy)), axes, rng.uniform(0, 180), 0, 360, 1.0, -1)
        _blend(img, mask, (25, 45, 70), 0.75 * severity)
        p1 = (int(cx + ox - 6), int(cy + oy - 4))
        p2 = (int(cx + ox + 6), int(cy + oy + 4))
        cv2.line(img, p1, p2, (20, 35, 55), 1)
    elif kind == "tear":
        idx = int(rng.integers(0, 4))
        a, b = poly[idx].astype(float), poly[(idx + 1) % 4].astype(float)
        pts = []
        for t in np.linspace(0.15, 0.85, 7):
            p = a + (b - a) * t
            inward = (np.array([cx, cy]) - p)
            inward = inward / (np.linalg.norm(inward) + 1e-6)
            pts.append(p + inward * rng.uniform(1, 6 * severity + 1))
        pts_arr = np.array(pts + [a + (b - a) * 0.5], dtype=np.int32)
        cv2.fillPoly(img, [pts_arr], (15, 15, 20))
        cv2.polylines(img, [pts_arr], False, (200, 220, 235), 1)
    elif kind == "stain":
        for _ in range(3):
            ox, oy = rng.uniform(-9, 9, 2)
            cv2.circle(mask, (int(cx + ox), int(cy + oy)), int(rng.uniform(3, 8)), 1.0, -1)
        _blend(img, mask, (35, 70, 60), 0.6 * severity)
    elif kind == "crushed_corner":
        idx = int(rng.integers(0, 4))
        corner = poly[idx].astype(float)
        n1, n2 = poly[(idx + 1) % 4].astype(float), poly[idx - 1].astype(float)
        cut = int(rng.uniform(4, 10) * severity + 2)
        p1 = corner + (n1 - corner) / (np.linalg.norm(n1 - corner) + 1e-6) * cut
        p2 = corner + (n2 - corner) / (np.linalg.norm(n2 - corner) + 1e-6) * cut
        tri = np.array([corner, p1, p2], dtype=np.int32)
        bg = img[max(int(corner[1]) - 2, 0), max(int(corner[0]) - 2, 0)].tolist()
        cv2.fillPoly(img, [tri], bg)
        cv2.line(img, tuple(p1.astype(int)), tuple(p2.astype(int)), (30, 50, 80), 1)


def render_package(rng: np.random.Generator, damaged: bool, size: int = IMAGE_SIZE) -> np.ndarray:
    """Retourne une image BGR uint8 (size, size, 3)."""
    base = rng.uniform(90, 200)
    img = np.full((size, size, 3), base, np.float32)
    img += rng.normal(0, 6, img.shape)
    img = np.clip(img, 0, 255).astype(np.uint8)

    if rng.random() < 0.4:  # ombre portée
        shadow = np.zeros((size, size), np.float32)
        cv2.ellipse(shadow, (size // 2, int(size * 0.85)), (int(size * 0.3), 4), 0, 0, 360, 1.0, -1)
        _blend(img, shadow, (40, 40, 40), 0.35)

    poly = _box_polygon(rng, size)
    brown = (int(rng.normal(60, 12)), int(rng.normal(110, 12)), int(rng.normal(160, 12)))
    cv2.fillPoly(img, [poly], brown)
    cv2.polylines(img, [poly], True, (30, 60, 95), 1)

    cx, cy = poly.mean(axis=0).astype(int)
    cv2.line(img, (cx - 14, cy), (cx + 14, cy), (170, 200, 215), 3)  # ruban adhésif
    cv2.rectangle(img, (cx - 9, cy + 5), (cx + 3, cy + 13), (235, 235, 235), -1)  # étiquette

    if rng.random() < 0.3:  # autocollant bénin
        color = tuple(int(c) for c in rng.integers(60, 255, 3))
        cv2.rectangle(img, (cx + 5, cy - 14), (cx + 12, cy - 8), color, -1)
    if rng.random() < 0.3:  # pli discret bénin
        cv2.line(img, (cx - 12, cy - 8), (cx + 4, cy - 12), (45, 85, 125), 1)

    if damaged:
        n = 1 if rng.random() < 0.7 else 2
        for kind in rng.choice(DAMAGE_TYPES, size=n, replace=False):
            severity = rng.uniform(0.45, 1.0)  # une partie des dommages est subtile
            _apply_damage(img, poly, rng, str(kind), severity)

    img = cv2.convertScaleAbs(img, alpha=rng.uniform(0.8, 1.2), beta=rng.uniform(-15, 15))
    noise = rng.normal(0, 4, img.shape)
    img = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    if rng.random() < 0.3:
        img = cv2.GaussianBlur(img, (3, 3), 0)
    return img


def generate_dataset(n: int, seed: int = 0, damaged_fraction: float = 0.5):
    """(images uint8 [n,H,W,3], labels int [n]) — 1 = endommagé."""
    rng = np.random.default_rng(seed)
    labels = (rng.random(n) < damaged_fraction).astype(int)
    images = np.stack([render_package(rng, bool(lbl)) for lbl in labels])
    return images, labels

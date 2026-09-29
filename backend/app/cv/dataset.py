"""Chargement d'un dataset d'images depuis un dossier (données réelles).

Structure attendue : <dossier>/normal/*.jpg|png et <dossier>/damaged/*.jpg|png.
C'est le point d'entrée pour brancher Parcel3D (Zenodo) ou un export
Roboflow "classification" à la place des images synthétiques.
"""

from pathlib import Path

import cv2
import numpy as np

from app.cv.synthetic import IMAGE_SIZE

EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}


def load_image_folder(folder: Path, size: int = IMAGE_SIZE):
    images, labels = [], []
    for label, name in enumerate(("normal", "damaged")):
        for path in sorted((folder / name).glob("*")):
            if path.suffix.lower() not in EXTENSIONS:
                continue
            img = cv2.imread(str(path))
            if img is None:
                continue
            images.append(cv2.resize(img, (size, size)))
            labels.append(label)
    if not images:
        raise ValueError(f"Aucune image trouvée dans {folder}/normal et {folder}/damaged.")
    return np.stack(images), np.array(labels)


def save_dataset(images: np.ndarray, labels: np.ndarray, folder: Path) -> None:
    for name in ("normal", "damaged"):
        (folder / name).mkdir(parents=True, exist_ok=True)
    for i, (img, label) in enumerate(zip(images, labels, strict=True)):
        cv2.imwrite(str(folder / ("damaged" if label else "normal") / f"img_{i:05d}.png"), img)

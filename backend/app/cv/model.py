"""CNN de classification colis normal / endommagé (Phase 5).

Architecture volontairement petite (3 blocs conv, ~50k paramètres) :
les images sont 64x64 synthétiques, un ResNet pré-entraîné serait hors
de proportion et de toute façon impossible à télécharger ici (les poids
PyTorch/Keras hébergés sur download.pytorch.org et storage.googleapis
renvoient 403 depuis cet environnement — cf. ADR-011).
"""

import tensorflow as tf

from app.cv.synthetic import IMAGE_SIZE


def build_cnn(input_size: int = IMAGE_SIZE) -> tf.keras.Model:
    inputs = tf.keras.Input(shape=(input_size, input_size, 3))
    x = tf.keras.layers.Rescaling(1.0 / 255)(inputs)
    # Augmentation légère : un dommage reste un dommage retourné/pivoté
    # un peu — régularisation label-preserving, quasi gratuite, utile
    # vu le peu d'images d'entraînement (cf. ADR-011, surapprentissage
    # observé sans elle : accuracy train 78% / val ~50%).
    x = tf.keras.layers.RandomFlip("horizontal")(x)
    x = tf.keras.layers.RandomRotation(0.03)(x)
    for filters in (16, 32, 64):
        x = tf.keras.layers.Conv2D(filters, 3, padding="same", activation="relu")(x)
        x = tf.keras.layers.BatchNormalization()(x)
        x = tf.keras.layers.MaxPooling2D()(x)
    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.Dense(32, activation="relu")(x)
    x = tf.keras.layers.Dropout(0.4)(x)
    outputs = tf.keras.layers.Dense(1, activation="sigmoid")(x)

    model = tf.keras.Model(inputs, outputs, name="package_damage_cnn")
    model.compile(
        optimizer=tf.keras.optimizers.Adam(5e-4),
        loss="binary_crossentropy",
        metrics=["accuracy"],
    )
    return model

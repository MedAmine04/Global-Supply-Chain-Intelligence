"""Feature engineering — prédiction de retard d'expédition (FR-11).

RÈGLE ABSOLUE DE CE MODULE : aucune feature ne doit utiliser une
information qui ne serait pas connue au moment où l'expédition part
(`ship_date`). C'est le piège n°1 d'un projet ML supply chain : calculer
le "taux de retard historique du fournisseur" en incluant l'expédition
elle-même (ou des expéditions plus tardives) donne un modèle qui a l'air
excellent en test mais qui est inutilisable en production, puisque ces
informations n'existent pas encore au moment de la prédiction réelle.

Toutes les features "historiques" (`supplier_delay_rate`,
`previous_incidents_count`) sont donc calculées strictement à partir des
expéditions *antérieures* du même fournisseur (ship_date strictement
inférieure), jamais de l'expédition courante ni des suivantes. Vérifié
explicitement par `tests/test_ml_features.py`, pas seulement supposé.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

FEATURE_COLUMNS = [
    "distance_km",
    "quantity",
    "warehouse_capacity",
    "transport_mode",
    "season",
    "day_of_week",
    "supplier_delay_rate",
    "supplier_prior_shipment_count",
    "previous_incidents_count",
]

TARGET_COLUMN = "is_delayed"


def _season(month: int) -> str:
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


_RAW_SHIPMENT_COLUMNS = [
    "shipment_id", "supplier_sk", "ship_date", "distance_km", "is_delayed",
    "transport_mode", "quantity", "warehouse_capacity",
]


def _fetch_raw_shipments(db: Session, only_undelivered: bool = False) -> pd.DataFrame:
    """Une ligne par expédition, avec les attributs connus dès le départ
    (distance, transport, quantité commandée, capacité entrepôt) + le
    résultat (is_delayed) quand il est connu.

    `only_undelivered=True` : ne retourne que les expéditions sans
    résultat encore connu (pas de date de livraison réelle) — c'est
    l'ensemble à scorer par le modèle en production, par opposition à
    l'ensemble d'entraînement (`only_undelivered=False`, qui filtre au
    contraire sur les expéditions déjà livrées, donc au résultat connu).
    """
    condition = (
        "fs.actual_delivery_date IS NULL" if only_undelivered
        else "fs.actual_delivery_date IS NOT NULL"
    )
    query = text(f"""
        SELECT
            fs.shipment_id,
            fs.supplier_sk,
            fs.ship_date,
            fs.distance_km,
            fs.is_delayed,
            dt.transport_mode,
            fo.quantity,
            dw.capacity AS warehouse_capacity
        FROM fact_shipments fs
        JOIN dim_transport dt ON dt.transport_sk = fs.transport_sk
        JOIN dim_warehouse dw ON dw.warehouse_sk = fs.warehouse_sk
        LEFT JOIN fact_orders fo ON fo.order_id = fs.order_id
        WHERE fs.ship_date IS NOT NULL AND {condition}
    """)
    rows = db.execute(query).mappings().all()
    # Même piège que pour Spark (cf. app/services/spark_transform.py) :
    # pd.DataFrame([]) sans schéma explicite casse tout accès ultérieur
    # par nom de colonne (`df["ship_date"]`) dès que le résultat est
    # vide — ce qui arrive réellement quand aucune expédition n'a encore
    # été livrée (cold start du pipeline, ou scénario de test minimal).
    return pd.DataFrame(rows, columns=_RAW_SHIPMENT_COLUMNS)


def _fetch_incident_timeline(db: Session) -> pd.DataFrame:
    """Une ligne par incident, avec le fournisseur et la ship_date de
    l'expédition concernée — nécessaire pour compter, pour chaque
    expédition, le nombre d'incidents *antérieurs* du même fournisseur."""
    query = text("""
        SELECT fs.supplier_sk, fs.ship_date
        FROM fact_incidents fi
        JOIN fact_shipments fs ON fs.shipment_id = fi.shipment_id
        WHERE fs.ship_date IS NOT NULL
        ORDER BY fs.supplier_sk, fs.ship_date
    """)
    rows = db.execute(query).mappings().all()
    return pd.DataFrame(rows, columns=["supplier_sk", "ship_date"])


def _add_prior_supplier_delay_rate(df: pd.DataFrame) -> pd.DataFrame:
    """Pour chaque expédition, taux de retard des expéditions
    *antérieures* du même fournisseur uniquement (shift(1) exclut la
    ligne courante ; expanding() ne regarde que les lignes précédentes
    dans l'ordre trié par ship_date — donc jamais le futur)."""
    df = df.sort_values(["supplier_sk", "ship_date"]).reset_index(drop=True)
    df["supplier_prior_shipment_count"] = df.groupby("supplier_sk").cumcount()

    def _expanding_prior_mean(s: pd.Series) -> pd.Series:
        return s.shift(1).expanding().mean()

    df["supplier_delay_rate"] = df.groupby("supplier_sk")["is_delayed_numeric"].transform(
        _expanding_prior_mean
    )
    return df


def _add_previous_incidents_count(df: pd.DataFrame, incidents_df: pd.DataFrame) -> pd.DataFrame:
    """Pour chaque expédition, nombre d'incidents antérieurs (même
    fournisseur, ship_date de l'incident strictement inférieure à celle
    de l'expédition courante), via recherche binaire sur la timeline
    triée des incidents de ce fournisseur."""
    counts = []
    if incidents_df.empty:
        df["previous_incidents_count"] = 0
        return df

    incidents_by_supplier = {
        supplier_sk: np.sort(group["ship_date"].values.astype("datetime64[ns]").astype("int64"))
        for supplier_sk, group in incidents_df.groupby("supplier_sk")
    }

    for _, row in df.iterrows():
        timeline = incidents_by_supplier.get(row["supplier_sk"])
        if timeline is None:
            counts.append(0)
        else:
            row_ts = np.datetime64(row["ship_date"], "ns").astype("int64")
            counts.append(int(np.searchsorted(timeline, row_ts, side="left")))

    df["previous_incidents_count"] = counts
    return df


@dataclass
class FeatureDataset:
    # colonnes : FEATURE_COLUMNS + shipment_id + ship_date (+ TARGET_COLUMN si has_target)
    df: pd.DataFrame
    has_target: bool


def build_feature_dataset(db: Session, only_undelivered: bool = False) -> FeatureDataset:
    raw = _fetch_raw_shipments(db, only_undelivered=only_undelivered)
    if raw.empty:
        empty_df = pd.DataFrame(columns=["shipment_id", *FEATURE_COLUMNS])
        return FeatureDataset(empty_df, has_target=not only_undelivered)

    raw["ship_date"] = pd.to_datetime(raw["ship_date"])
    if only_undelivered:
        # NaN, pas 0 : une expédition non livrée n'a pas de résultat
        # connu. La mettre à 0 biaiserait artificiellement le taux de
        # retard historique calculé pour une AUTRE expédition du même
        # fournisseur plus tardive dans le même batch de scoring (le
        # calcul ci-dessous inclut l'historique complet, y compris les
        # expéditions non livrées qui précèdent chronologiquement).
        # NaN est correctement ignoré par `expanding().mean()`.
        raw["is_delayed_numeric"] = np.nan
    else:
        raw["is_delayed_numeric"] = raw["is_delayed"].astype("boolean").astype("Int64")

    incidents_df = _fetch_incident_timeline(db)
    if not incidents_df.empty:
        incidents_df["ship_date"] = pd.to_datetime(incidents_df["ship_date"])

    # Le calcul des features historiques utilise TOUJOURS l'historique
    # complet disponible à ce jour (y compris, pour une expédition à
    # scorer, les expéditions déjà livrées du même fournisseur) : c'est
    # exactement l'information dont on disposerait réellement au moment
    # de la prédiction en production.
    if only_undelivered:
        history = _fetch_raw_shipments(db, only_undelivered=False)
        history["ship_date"] = pd.to_datetime(history["ship_date"])
        history["is_delayed_numeric"] = history["is_delayed"].astype("boolean").astype("Int64")
        # Cast explicite en float64 des deux côtés avant concat : évite un
        # FutureWarning pandas sur la concaténation d'une colonne
        # entièrement NaN (celle de `raw`, cf. commentaire ci-dessus) et
        # rend le comportement futur de pandas non ambigu dès maintenant.
        history["is_delayed_numeric"] = history["is_delayed_numeric"].astype("float64")
        raw["is_delayed_numeric"] = raw["is_delayed_numeric"].astype("float64")
        combined = pd.concat([history, raw], ignore_index=True, sort=False)
        combined = _add_prior_supplier_delay_rate(combined)
        combined = _add_previous_incidents_count(combined, incidents_df)
        df = combined[combined["shipment_id"].isin(raw["shipment_id"])].copy()
    else:
        df = _add_prior_supplier_delay_rate(raw)
        df = _add_previous_incidents_count(df, incidents_df)

    df["season"] = df["ship_date"].dt.month.apply(_season)
    df["day_of_week"] = df["ship_date"].dt.dayofweek

    df["is_delayed"] = df["is_delayed_numeric"] if not only_undelivered else df["is_delayed"]

    output_columns = ["shipment_id", "ship_date", *FEATURE_COLUMNS]
    if not only_undelivered:
        output_columns.append(TARGET_COLUMN)

    return FeatureDataset(df[output_columns].copy(), has_target=not only_undelivered)

"""Transformation fact_shipments via Spark (Phase 2 — Big Data).

Réimplémentation de `gold_transform.transform_fact_shipments` avec
l'API DataFrame de Spark, pour appliquer réellement le framework plutôt
que de l'ajouter au projet sans l'utiliser pour un vrai calcul.

Portée volontairement limitée (cf. ADR-006) :
- L'extraction depuis Silver et l'écriture dans Gold passent toujours
  par SQLAlchemy, PAS par un connecteur JDBC Spark->PostgreSQL : aucun
  driver JDBC PostgreSQL n'est récupérable dans cet environnement réseau
  restreint (pas d'accès à un dépôt Maven). Spark est donc utilisé pour
  le calcul (jointures, dérivation de mesures), pas pour l'I/O.
- Un seul fait (fact_shipments) est réécrit en Spark, pas tout le
  pipeline Gold : c'est le fait le plus complexe (4 jointures de
  dimensions + mesures dérivées), donc celui qui justifie le mieux
  l'usage de Spark à ce stade pédagogique.
"""

from dataclasses import dataclass

import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, StringType, StructField, StructType
from sqlalchemy.orm import Session

from app.models.gold import DimProduct, DimSupplier, DimTransport, DimWarehouse, FactShipment
from app.models.silver import SilverOrder, SilverShipment
from app.services.gold_transform import _upsert

_spark: SparkSession | None = None


def get_spark() -> SparkSession:
    """SparkSession partagée (coûteuse à créer, pas de raison d'en
    recréer une par appel)."""
    global _spark
    if _spark is None:
        _spark = (
            SparkSession.builder.appName("gsci-fact-shipments")
            .master("local[*]")
            .config("spark.ui.enabled", "false")
            .getOrCreate()
        )
        _spark.sparkContext.setLogLevel("WARN")
    return _spark


def _query_to_pandas(db: Session, query) -> pd.DataFrame:
    """Convertit une requête SQLAlchemy en DataFrame pandas (pont vers Spark)."""
    rows = query.all()
    if not rows:
        return pd.DataFrame()
    columns = [c.name for c in rows[0].__table__.columns]
    return pd.DataFrame([{c: getattr(r, c) for c in columns} for r in rows])


def _small_lookup_to_spark(spark: SparkSession, rows, id_col: str, sk_col: str, id_type=StringType):
    """Construit un DataFrame Spark à schéma explicite pour une petite
    dimension (supplier/warehouse/transport), directement depuis les
    objets ORM plutôt que via pandas.

    Nécessaire car la conversion pandas -> Spark plante sur un DataFrame
    pandas sans aucune ligne (`pd.DataFrame()` n'a pas de schéma inférable) :
    un schéma Spark explicite fonctionne aussi bien avec zéro ligne
    qu'avec des milliers, ce qui évite ce piège pour de bon plutôt que de
    le contourner au cas par cas."""
    schema = StructType([
        StructField(id_col, id_type(), True),
        StructField(sk_col, IntegerType(), True),
    ])
    data = [(getattr(r, id_col), getattr(r, sk_col)) for r in rows]
    return spark.createDataFrame(data, schema=schema)


@dataclass
class SparkTransformResult:
    rows_considered: int
    rows_skipped_invalid: int
    rows_created: int
    rows_updated: int


def transform_fact_shipments_spark(db: Session) -> SparkTransformResult:
    spark = get_spark()

    shipments_pd = _query_to_pandas(db, db.query(SilverShipment))
    orders_pd = _query_to_pandas(db, db.query(SilverOrder))
    suppliers_rows = db.query(DimSupplier).all()
    warehouses_rows = db.query(DimWarehouse).all()
    transports_rows = db.query(DimTransport).all()

    rows_considered = len(shipments_pd)
    if rows_considered == 0:
        return SparkTransformResult(0, 0, 0, 0)

    # Spark ne gère pas nativement les colonnes de type `date` Python
    # extraites de pandas comme des objets ; on convertit explicitement
    # en chaîne ISO avant de passer à Spark, puis on recaste en `date`
    # côté Spark — plus robuste que de laisser l'inférence de schéma deviner.
    for col in ["ship_date", "expected_delivery_date", "actual_delivery_date"]:
        shipments_pd[col] = shipments_pd[col].astype(str).replace("None", None)
    if orders_pd.empty:
        orders_pd = pd.DataFrame(columns=["order_id", "supplier_id", "product_id"])
    else:
        orders_pd["order_date"] = orders_pd["order_date"].astype(str).replace("None", None)

    shipments = spark.createDataFrame(shipments_pd).withColumn(
        "actual_delivery_date", F.to_date("actual_delivery_date")
    ).withColumn(
        "expected_delivery_date", F.to_date("expected_delivery_date")
    )
    orders = spark.createDataFrame(orders_pd).select(
        F.col("order_id"), F.col("supplier_id"), F.col("product_id")
    )
    suppliers = _small_lookup_to_spark(spark, suppliers_rows, "supplier_id", "supplier_sk")
    warehouses = _small_lookup_to_spark(spark, warehouses_rows, "warehouse_id", "warehouse_sk")
    transports = _small_lookup_to_spark(spark, transports_rows, "transport_mode", "transport_sk")

    joined = (
        shipments
        .join(orders, on="order_id", how="left")
        .join(suppliers, on="supplier_id", how="left")
        .join(warehouses, on="warehouse_id", how="left")
        .join(transports, on="transport_mode", how="left")
    )

    valid = joined.filter(
        F.col("supplier_sk").isNotNull()
        & F.col("warehouse_sk").isNotNull()
        & F.col("transport_sk").isNotNull()
    )
    skipped_count = joined.count() - valid.count()

    # Mesures dérivées calculées en Spark (équivalent du calcul Python de
    # gold_transform.transform_fact_shipments, exprimé en DataFrame API).
    result_df = valid.withColumn(
        "delay_days",
        F.when(
            F.col("actual_delivery_date").isNotNull() & F.col("expected_delivery_date").isNotNull(),
            F.datediff(F.col("actual_delivery_date"), F.col("expected_delivery_date")),
        ),
    ).withColumn(
        "is_delayed",
        F.when(F.col("delay_days").isNotNull(), F.col("delay_days") > 0),
    )

    # Note : product_sk manque encore au schéma de fact_shipments dans ce
    # calcul (product_id non résolu ici pour rester concentré sur la
    # démonstration Spark) — on le fusionne côté pandas juste après en
    # récupérant la valeur telle quelle depuis Silver, cohérent avec
    # l'implémentation ORM existante.
    dim_product_sk = {p.product_id: p.product_sk for p in db.query(DimProduct).all()}

    pdf = result_df.select(
        "shipment_id", "order_id", "supplier_sk", "warehouse_sk", "transport_sk",
        "product_id", "ship_date", "expected_delivery_date", "actual_delivery_date",
        "distance_km", "is_delayed", "delay_days",
    ).toPandas()

    rows_created = rows_updated = 0
    for row in pdf.itertuples(index=False):
        product_sk = dim_product_sk.get(row.product_id)
        if product_sk is None:
            skipped_count += 1
            continue
        _, was_created = _upsert(
            db, FactShipment, "shipment_id", row.shipment_id,
            order_id=row.order_id,
            supplier_sk=int(row.supplier_sk),
            product_sk=product_sk,
            warehouse_sk=int(row.warehouse_sk),
            transport_sk=int(row.transport_sk),
            ship_date=pd.Timestamp(row.ship_date).date() if pd.notna(row.ship_date) else None,
            expected_delivery_date=(
                pd.Timestamp(row.expected_delivery_date).date()
                if pd.notna(row.expected_delivery_date) else None
            ),
            actual_delivery_date=(
                pd.Timestamp(row.actual_delivery_date).date()
                if pd.notna(row.actual_delivery_date) else None
            ),
            distance_km=row.distance_km,
            is_delayed=bool(row.is_delayed) if pd.notna(row.is_delayed) else None,
            delay_days=int(row.delay_days) if pd.notna(row.delay_days) else None,
        )
        rows_created += was_created
        rows_updated += not was_created

    db.commit()

    return SparkTransformResult(
        rows_considered=rows_considered,
        rows_skipped_invalid=skipped_count,
        rows_created=rows_created,
        rows_updated=rows_updated,
    )

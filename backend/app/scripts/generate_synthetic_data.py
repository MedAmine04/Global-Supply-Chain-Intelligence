"""Génère un dataset synthétique réaliste pour le développement local.

Usage:
    python -m app.scripts.generate_synthetic_data --out data/raw --scale small

Les volumes sont volontairement réduits par rapport à la cible finale
(cf. blueprint : 10k suppliers / 100k products / 5M orders / 10M shipments)
pour rester rapide à régénérer en développement. Le schéma relationnel
(clés étrangères logiques entre suppliers/products/warehouses/orders/
shipments/incidents) est respecté pour que le pipeline Silver/Gold ait
de vraies données à joindre.
"""

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker

fake = Faker()
Faker.seed(42)
random.seed(42)

SCALES = {
    "small": {
        "suppliers": 200, "products": 1000, "warehouses": 20,
        "orders": 5000, "incident_rate": 0.08,
    },
    "medium": {
        "suppliers": 2000, "products": 10000, "warehouses": 80,
        "orders": 50000, "incident_rate": 0.08,
    },
}

TRANSPORT_MODES = ["road", "sea", "air", "rail"]
ORDER_STATUSES = ["pending", "confirmed", "shipped", "delivered", "cancelled"]
INCIDENT_TYPES = ["CUSTOMS_DELAY", "DAMAGE", "LOST", "WEATHER", "MECHANICAL", "DOCUMENTATION"]
SEVERITIES = ["low", "medium", "high"]

# Quelques valeurs "sales" volontaires, injectées à faible taux, pour que
# FR-02 (Data Quality) ait de vrais problèmes à détecter dès le premier run.
DIRTY_RATE = 0.03


def _maybe_dirty(value: str) -> str:
    if random.random() < DIRTY_RATE:
        return random.choice(["", None, "N/A", "  "])
    return value


def generate_suppliers(n: int) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        rows.append(
            {
                "supplier_id": f"SUP-{i:06d}",
                "name": fake.company(),
                "country": fake.country(),
                "reliability_score": _maybe_dirty(str(round(random.uniform(0.4, 0.99), 2))),
                "created_at": fake.date_between(start_date="-3y", end_date="-6M").isoformat(),
            }
        )
    return rows


def generate_products(n: int) -> list[dict]:
    categories = ["electronics", "apparel", "food", "furniture", "automotive", "pharma"]
    rows = []
    for i in range(1, n + 1):
        rows.append(
            {
                "product_id": f"PRD-{i:06d}",
                "name": fake.word().capitalize() + " " + fake.word().capitalize(),
                "category": random.choice(categories),
                "unit_cost": _maybe_dirty(str(round(random.uniform(2, 500), 2))),
            }
        )
    return rows


def generate_warehouses(n: int) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        rows.append(
            {
                "warehouse_id": f"WH-{i:04d}",
                "name": f"{fake.city()} Distribution Center",
                "country": fake.country(),
                "region": random.choice(["EMEA", "APAC", "AMERICAS"]),
                "capacity": str(random.randint(5000, 200000)),
            }
        )
    return rows


def generate_orders(
    n: int, supplier_ids: list[str], product_ids: list[str], warehouse_ids: list[str]
) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        order_date = fake.date_between(start_date="-1y", end_date="today")
        rows.append(
            {
                "order_id": f"ORD-{i:07d}",
                "supplier_id": random.choice(supplier_ids),
                "product_id": random.choice(product_ids),
                # petit % de FK cassées volontaires (warehouse inexistant) pour FR-02
                "warehouse_id": (
                    random.choice(warehouse_ids) if random.random() > 0.01 else "WH-9999"
                ),
                "order_date": order_date.isoformat(),
                "quantity": _maybe_dirty(str(random.randint(1, 5000))),
                "status": random.choice(ORDER_STATUSES),
            }
        )
    return rows


def generate_shipments(orders: list[dict]) -> list[dict]:
    rows = []
    for idx, order in enumerate(orders, start=1):
        if order["status"] not in ("shipped", "delivered"):
            continue
        ship_date = datetime.fromisoformat(order["order_date"]) + timedelta(
            days=random.randint(1, 5)
        )
        transit_days = random.randint(2, 30)
        expected = ship_date + timedelta(days=transit_days)
        is_late = random.random() < 0.22
        actual = (
            expected + timedelta(days=random.randint(1, 10))
            if is_late
            else expected - timedelta(days=random.randint(0, 1))
        )
        rows.append(
            {
                "shipment_id": f"SHP-{idx:07d}",
                "order_id": order["order_id"],
                "warehouse_id": order["warehouse_id"],
                "transport_mode": random.choice(TRANSPORT_MODES),
                "origin": fake.city(),
                "destination": fake.city(),
                "ship_date": ship_date.date().isoformat(),
                "expected_delivery_date": expected.date().isoformat(),
                "actual_delivery_date": actual.date().isoformat()
                if order["status"] == "delivered"
                else None,
                "distance_km": _maybe_dirty(str(random.randint(50, 15000))),
            }
        )
    return rows


def generate_incidents(shipments: list[dict], rate: float) -> list[dict]:
    rows = []
    i = 0
    for shipment in shipments:
        if random.random() < rate:
            i += 1
            rows.append(
                {
                    "incident_id": f"INC-{i:06d}",
                    "shipment_id": shipment["shipment_id"],
                    "incident_type": random.choice(INCIDENT_TYPES),
                    "description": fake.sentence(nb_words=12),
                    "incident_date": shipment["ship_date"],
                    "severity": random.choice(SEVERITIES),
                }
            )
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    import csv

    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Génère le dataset synthétique GSCI.")
    parser.add_argument("--out", default="data/raw", help="Dossier de sortie")
    parser.add_argument("--scale", choices=SCALES.keys(), default="small")
    args = parser.parse_args()

    cfg = SCALES[args.scale]
    out_dir = Path(args.out)

    suppliers = generate_suppliers(cfg["suppliers"])
    products = generate_products(cfg["products"])
    warehouses = generate_warehouses(cfg["warehouses"])
    orders = generate_orders(
        cfg["orders"],
        [s["supplier_id"] for s in suppliers],
        [p["product_id"] for p in products],
        [w["warehouse_id"] for w in warehouses],
    )
    shipments = generate_shipments(orders)
    incidents = generate_incidents(shipments, cfg["incident_rate"])

    write_csv(suppliers, out_dir / "suppliers.csv")
    write_csv(products, out_dir / "products.csv")
    write_csv(warehouses, out_dir / "warehouses.csv")
    write_csv(orders, out_dir / "orders.csv")
    write_csv(shipments, out_dir / "shipments.csv")
    write_csv(incidents, out_dir / "incidents.csv")

    print(f"Generated: {len(suppliers)} suppliers, {len(products)} products, "
          f"{len(warehouses)} warehouses, {len(orders)} orders, "
          f"{len(shipments)} shipments, {len(incidents)} incidents -> {out_dir}")


if __name__ == "__main__":
    main()

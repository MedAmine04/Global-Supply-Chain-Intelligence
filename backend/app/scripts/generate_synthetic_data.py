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


def _supplier_reliability_lookup(suppliers: list[dict]) -> dict[str, float]:
    """Convertit reliability_score (str, potentiellement sale à cause de
    _maybe_dirty) en float, avec une valeur par défaut neutre pour les
    entrées sales — ces dernières ne doivent pas casser la génération,
    seulement rester détectables par FR-02 en aval."""
    lookup = {}
    for s in suppliers:
        try:
            lookup[s["supplier_id"]] = float(s["reliability_score"])
        except (TypeError, ValueError):
            lookup[s["supplier_id"]] = 0.7
    return lookup


def generate_shipments(orders: list[dict], supplier_reliability: dict[str, float]) -> list[dict]:
    """Génère les expéditions avec un risque de retard qui dépend
    réellement de la fiabilité du fournisseur, du mode de transport et
    de la distance — pas un taux fixe indépendant de tout.

    Sans ce lien causal, aucun modèle ne peut apprendre quoi que ce
    soit d'utile sur ce dataset (un taux de retard purement aléatoire
    et indépendant des features donne un ROC-AUC ~0.5 par construction,
    peu importe la qualité du feature engineering ou du modèle — vérifié
    concrètement lors du premier entraînement, cf. ADR-009). Les
    coefficients ci-dessous sont un choix arbitraire mais documenté,
    pas ajustés a posteriori pour obtenir un bon score.
    """
    rows = []
    for idx, order in enumerate(orders, start=1):
        if order["status"] not in ("shipped", "delivered"):
            continue
        ship_date = datetime.fromisoformat(order["order_date"]) + timedelta(
            days=random.randint(1, 5)
        )
        transit_days = random.randint(2, 30)
        expected = ship_date + timedelta(days=transit_days)
        distance_km = random.randint(50, 15000)
        transport_mode = random.choice(TRANSPORT_MODES)

        reliability = supplier_reliability.get(order["supplier_id"], 0.7)
        transport_risk = {"air": -0.05, "rail": 0.02, "road": 0.03, "sea": 0.08}[transport_mode]
        delay_probability = (
            0.10
            + (1 - reliability) * 0.40
            + transport_risk
            + (distance_km / 15000) * 0.15
        )
        delay_probability = min(max(delay_probability, 0.02), 0.85)

        is_late = random.random() < delay_probability
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
                "transport_mode": transport_mode,
                "origin": fake.city(),
                "destination": fake.city(),
                "ship_date": ship_date.date().isoformat(),
                "expected_delivery_date": expected.date().isoformat(),
                "actual_delivery_date": actual.date().isoformat()
                if order["status"] == "delivered"
                else None,
                "distance_km": _maybe_dirty(str(distance_km)),
            }
        )
    return rows



# Gabarits de descriptions d'incidents liés au type (Phase 4 — NLP).
# Sans lien texte <-> type, aucun classifieur ne pourrait rien apprendre
# (même piège que pour le générateur de retards, cf. ADR-009). Les
# vocabulaires se recouvrent volontairement entre types (ex. "customs"
# apparaît en CUSTOMS_DELAY et en DOCUMENTATION) et ~10% des textes sont
# génériques, pour que la tâche ne soit pas triviale.
DURATION_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 7: "seven"}
INCIDENT_TEMPLATES = {
    "CUSTOMS_DELAY": [
        "Shipment {sid} was delayed for {dur} because customs clearance "
        "took longer than expected in {city}.",
        "{sid} held at customs in {city} for {dur} pending inspection.",
        "Customs officers in {city} kept {sid} for {dur} for additional checks.",
    ],
    "DOCUMENTATION": [
        "{sid} was held for {dur} in {city} because paperwork was missing.",
        "Incorrect invoice forced {sid} to wait {dur} at the {city} border.",
        "Missing customs documents delayed {sid} by {dur} in {city}.",
    ],
    "WEATHER": [
        "A storm near {city} delayed {sid} for {dur}.",
        "Heavy snow closed the route and {sid} waited {dur} in {city}.",
        "Severe weather in {city} stopped {sid} for {dur}.",
    ],
    "MECHANICAL": [
        "The truck carrying {sid} broke down near {city}, causing a delay of {dur}.",
        "Engine failure left {sid} stranded in {city} for {dur}.",
        "A vehicle breakdown in {city} delayed {sid} by {dur}.",
    ],
    "DAMAGE": [
        "{sid} arrived in {city} with crushed packaging and damaged goods.",
        "Goods in {sid} were damaged during handling in {city}; inspection took {dur}.",
        "Water damage found on {sid} at the {city} warehouse.",
    ],
    "LOST": [
        "{sid} could not be located after leaving {city}; search ongoing for {dur}.",
        "Carrier lost track of {sid} near {city} for {dur}.",
        "{sid} went missing in transit through {city}.",
    ],
}
GENERIC_INCIDENT_TEXTS = [
    "Issue reported by carrier for {sid}.",
    "{sid} requires follow-up with the logistics team.",
    "Incident logged for {sid}, details pending.",
]


def _incident_description(incident_type: str, shipment_id: str) -> str:
    if random.random() < 0.10:
        template = random.choice(GENERIC_INCIDENT_TEXTS)
    else:
        template = random.choice(INCIDENT_TEMPLATES[incident_type])
    days = random.choice(list(DURATION_WORDS))
    duration = f"{DURATION_WORDS[days]} day{'s' if days > 1 else ''}"
    if random.random() < 0.3:  # parfois en chiffres : "3 days"
        duration = f"{days} day{'s' if days > 1 else ''}"
    return template.format(sid=shipment_id, dur=duration, city=fake.city())


def generate_incidents(shipments: list[dict], rate: float) -> list[dict]:
    rows = []
    i = 0
    for shipment in shipments:
        if random.random() < rate:
            i += 1
            incident_type = random.choice(INCIDENT_TYPES)
            rows.append(
                {
                    "incident_id": f"INC-{i:06d}",
                    "shipment_id": shipment["shipment_id"],
                    "incident_type": incident_type,
                    "description": _incident_description(incident_type, shipment["shipment_id"]),
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
    shipments = generate_shipments(orders, _supplier_reliability_lookup(suppliers))
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

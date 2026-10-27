"""Freeze public inputs and independently constructed references before model runs."""

from __future__ import annotations

import copy
import json
import random
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "benchmarks" / "rubric-v1"


def money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def contacts(rng: random.Random, variant: int) -> tuple[dict, dict, None]:
    rows = []
    expected = []
    for index in range(3 + variant % 4):
        email = f"person{variant}-{index}@example.org"
        phone = str(rng.randint(10_000_000, 99_999_999))
        name = f"User {index}"
        rows.extend(
            [
                {
                    "email": f" {email.upper()} ",
                    "name": "" if index % 2 else f" User  {index} ",
                    "phone": "",
                    "tags": [" VIP ", "alpha"],
                },
                {
                    "email": email,
                    "name": name,
                    "phone": f"({phone[:3]})-{phone[3:]}",
                    "tags": ["vip", " BETA "],
                },
            ]
        )
        expected.append(
            {"email": email, "name": name, "phone": phone, "tags": ["alpha", "beta", "vip"]}
        )
    return {"contacts": rows}, {"contacts": sorted(expected, key=lambda row: row["email"])}, None


def invoice(rng: random.Random, variant: int) -> tuple[dict, dict, None]:
    rows = [
        {
            "id": chr(65 + index),
            "quantity": rng.randint(1, 7),
            "unit_price": rng.choice(["0.335", "5.555", "19.99", "12.345", "1.005"]),
            "discount_percent": rng.choice([0, 5, 10, 25]),
        }
        for index in range(2 + variant % 4)
    ]
    rng.shuffle(rows)
    nets = {
        row["id"]: (
            Decimal(row["quantity"])
            * Decimal(row["unit_price"])
            * (100 - Decimal(row["discount_percent"]))
            / 100
        ).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        for row in rows
    }
    subtotal = sum(nets.values(), Decimal(0))
    tax_rate = rng.choice(["0", "6", "13", "8.25"])
    tax = (subtotal * Decimal(tax_rate) / 100).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    total = subtotal + tax
    paid = [Decimal(0), total / 2, total, total + Decimal("1.00")][variant % 4]
    paid = paid.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    data = {"lines": rows, "tax_rate_percent": tax_rate, "payments": [money(paid)]}
    answer = {
        "lines": [{"id": key, "net": money(nets[key])} for key in sorted(nets)],
        "subtotal": money(subtotal),
        "tax": money(tax),
        "total": money(total),
        "paid": money(paid),
        "balance": money(total - paid),
        "status": "paid" if paid >= total else "partial" if paid else "unpaid",
    }
    return data, answer, None


def sales(rng: random.Random, variant: int) -> tuple[dict, dict, dict]:
    rows = []
    for index in range(8 + variant % 7):
        status = rng.choice(["paid", "paid", "pending", "refunded", "Paid"])
        rows.append(
            {
                "id": f"order-{variant}-{index}",
                "region": rng.choice(["west", "east", "north", "south"]),
                "status": status,
                "amount": rng.choice(["0.10", "0.20", "19.99", "10.01", "2.50"]),
            }
        )
    if variant % 6 == 0:
        for row in rows:
            row["status"] = "pending"
    if variant % 6 == 1:
        rows[0]["amount"] = "-1.25"
        rows[0]["status"] = "paid"
    batches = 2 + variant % 3
    files = {
        f"input/batch-{index}.json": json.dumps({"orders": rows[index::batches]}, indent=2) + "\n"
        for index in range(batches)
    }
    buckets = defaultdict(list)
    for row in rows:
        if row["status"] == "paid":
            buckets[row["region"]].append(Decimal(row["amount"]))
    regions = [
        {"region": name, "paid_orders": len(values), "revenue": money(sum(values, Decimal(0)))}
        for name, values in sorted(buckets.items())
    ]
    answer = {
        "regions": regions,
        "grand_total": money(sum((sum(v, Decimal(0)) for v in buckets.values()), Decimal(0))),
    }
    reference = {"files": {"output/summary.json": json.dumps(answer, indent=2) + "\n"}}
    return (
        {"input_glob": "/input/*.json", "output_path": "/output/summary.json"},
        reference,
        {"schema_version": "0.2", "directories": ["output"], "files": files},
    )


def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def main() -> None:
    if DESTINATION.exists():
        raise SystemExit("suite already exists; preserve it, or explicitly choose a new revision")
    families = [
        ("contacts", "structured.contacts-normalize.v1", contacts),
        ("invoice", "structured.invoice-reconcile.v1", invoice),
        ("sales", "file.sales-rollup.v1", sales),
    ]
    for split, count, offset in [("dev", 2, 0), ("holdout", 6, 100)]:
        cases = []
        for family, template, generator in families:
            public_base = yaml.safe_load((ROOT / f"benchmarks/public/{template}.yaml").read_text())
            private_base = yaml.safe_load(
                (ROOT / f"benchmarks/private/{template}.eval.yaml").read_text()
            )
            for index in range(count):
                variant = offset + index
                rng = random.Random(20261025 + variant * 37 + len(family))
                data, answer, fixture = generator(rng, variant)
                task_id = f"rubric.{family}.{split}.{index:02d}"
                public = copy.deepcopy(public_base)
                public.update(
                    id=task_id,
                    revision=1,
                    input=data,
                    tags=[family, split, "generated-instance", f"variant-{variant % 6}"],
                )
                public["limits"] = {
                    "actor_model_calls": 12,
                    "domain_tool_calls": 40,
                    "wall_clock_seconds": 240,
                }
                private = copy.deepcopy(private_base)
                private.update(task_ref=task_id + "@1", reference_submission=answer)
                if fixture is not None:
                    public["environment"]["fixture"] = f"../fixtures/{task_id}.yaml"
                    write_yaml(DESTINATION / "fixtures" / f"{task_id}.yaml", fixture)
                write_yaml(DESTINATION / "public" / f"{task_id}.yaml", public)
                write_yaml(DESTINATION / "private" / f"{task_id}.eval.yaml", private)
                cases.append(
                    {
                        "public": f"public/{task_id}.yaml",
                        "evaluation": f"private/{task_id}.eval.yaml",
                    }
                )
        write_yaml(
            DESTINATION / f"{split}.yaml",
            {"schema_version": "0.2", "name": f"rubric-v1-{split}", "cases": cases},
        )
    print("Frozen 6 development and 18 holdout instances across 3 task families.")


if __name__ == "__main__":
    main()

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import math
import random

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from tracker.models import PriceRecord, Product


class Command(BaseCommand):
    help = "Generate 1 year of fake daily price history for every product in the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=365,
            help="How many days of history to create per product (default: 365).",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete existing price records for the selected products before inserting fake data.",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default=None,
            help="Optional end date in YYYY-MM-DD format. Defaults to today.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        clear = options["clear"]
        end_date = self._parse_end_date(options["end_date"])

        products = Product.objects.select_related("source").all().order_by("id")
        total_products = products.count()

        if total_products == 0:
            self.stdout.write(self.style.WARNING("No products found in the database."))
            return

        start_date = end_date - timedelta(days=days - 1)

        self.stdout.write(
            f"Generating {days} days of fake history for {total_products} products "
            f"from {start_date} to {end_date}..."
        )

        created_total = 0

        for product in products:
            with transaction.atomic():
                if clear:
                    PriceRecord.objects.filter(product=product).delete()

                records = self._build_records(product, start_date, end_date)
                PriceRecord.objects.bulk_create(records, batch_size=1000)
                created_total += len(records)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created {created_total} price records for {total_products} products."
            )
        )

    def _parse_end_date(self, value: str | None) -> date:
        if not value:
            return timezone.localdate()
        return datetime.strptime(value, "%Y-%m-%d").date()

    def _build_records(self, product: Product, start_date: date, end_date: date) -> list[PriceRecord]:
        seed = self._stable_seed(product)
        rng = random.Random(seed)

        base_price = self._estimate_base_price(product, rng)
        trend_daily = rng.uniform(-0.18, 0.22)
        weekly_strength = rng.uniform(0.03, 0.09)
        monthly_strength = rng.uniform(0.02, 0.08)
        noise_strength = rng.uniform(0.01, 0.035)

        walk = 0.0
        records: list[PriceRecord] = []
        current = start_date

        while current <= end_date:
            days_from_start = (current - start_date).days
            weekday = current.weekday()
            month = current.month

            weekly_factor = 1.0 - weekly_strength if weekday in (5, 6) else 1.0 + weekly_strength / 2
            monthly_factor = 1.0 + monthly_strength * math.sin((month / 12.0) * 2 * math.pi)
            trend_factor = 1.0 + (trend_daily * days_from_start / 365.0)

            walk += rng.uniform(-noise_strength, noise_strength)
            daily_noise = rng.uniform(-noise_strength * 2, noise_strength * 2)

            price_float = base_price * weekly_factor * monthly_factor * trend_factor * (1.0 + walk + daily_noise)
            price_float = max(price_float, base_price * 0.35)

            price = Decimal(str(price_float)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            recorded_at = timezone.make_aware(datetime.combine(current, time(hour=12)))

            records.append(
                PriceRecord(
                    product=product,
                    source=product.source,
                    price=price,
                    raw_price_text=f"₹{price}",
                    recorded_at=recorded_at,
                )
            )
            current += timedelta(days=1)

        return records

    def _stable_seed(self, product: Product) -> int:
        raw = f"{product.id}|{product.external_id}|{product.name}|{product.brand}|{product.category}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return int(digest[:16], 16)

    def _estimate_base_price(self, product: Product, rng: random.Random) -> float:
        text = f"{product.name} {product.brand} {product.category}".lower()

        keyword_ranges = [
            (("phone", "smartphone", "mobile"), (8000, 35000)),
            (("laptop", "notebook", "ultrabook", "macbook", "chromebook"), (25000, 220000)),
            (("gaming", "rtx", "alienware", "rog"), (60000, 350000)),
            (("tablet", "ipad"), (10000, 70000)),
            (("charger", "adapter", "powerbank", "battery"), (399, 6999)),
            (("mouse", "keyboard", "pad"), (249, 5999)),
            (("bag", "backpack", "sleeve", "case", "cover", "pouch"), (199, 3999)),
            (("stand", "holder", "mount", "tripod", "riser"), (149, 3499)),
            (("warranty",), (499, 14999)),
            (("cooler", "fan", "cooling"), (499, 8999)),
            (("cable", "usb", "type-c", "otg", "hdmi", "enclosure"), (99, 3999)),
            (("monitor", "display", "screen"), (5000, 65000)),
            (("earphone", "headphone", "speaker"), (299, 29999)),
        ]

        for keywords, (low, high) in keyword_ranges:
            if any(k in text for k in keywords):
                return rng.uniform(low, high)

        base = 500 + (product.id % 5000) * 8
        return rng.uniform(max(199, base * 0.8), base * 1.2)
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import csv

from django.core.management.base import BaseCommand
from django.utils import timezone

from tracker.models import Product, PriceRecord, MarketplaceSource


class Command(BaseCommand):
    help = "Import Kaggle/Datafiniti price rows into Product and PriceRecord tables"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str)

    def handle(self, *args, **options):
        csv_path = options["csv_path"]

        source, _ = MarketplaceSource.objects.get_or_create(
            name="kaggle_datafiniti",
            defaults={"base_url": "https://www.kaggle.com/"}
        )

        created_products = 0
        created_records = 0
        skipped_rows = 0

        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)

            for row in reader:
                try:
                    name = (row.get("name") or "").strip()
                    brand = (row.get("brand") or "").strip()

                    if not name:
                        skipped_rows += 1
                        continue

                    asin = (row.get("asins") or "").split(",")[0].strip()
                    upc = (row.get("upc") or "").strip()
                    product_key = asin or upc or f"{brand}-{name}".lower()

                    image_urls = (row.get("imageURLs") or "").split(",")
                    image_url = image_urls[0].strip() if image_urls and image_urls[0] else ""

                    product, created = Product.objects.get_or_create(
                        external_id=product_key,
                        source=source,
                        defaults={
                            "name": name[:255],
                            "brand": brand[:255],
                            "category": (row.get("primaryCategories") or row.get("categories") or "")[:255],
                            "image_url": image_url,
                        },
                    )

                    if not product.image_url and image_url:
                        product.image_url = image_url
                        product.save()

                    if created:
                        created_products += 1

                    price_raw = row.get("prices.amountMin") or row.get("prices.amountMax")

                    if not price_raw:
                        skipped_rows += 1
                        continue

                    try:
                        price = Decimal(str(price_raw))
                    except (InvalidOperation, TypeError):
                        skipped_rows += 1
                        continue

                    if price < 50 or price > 300000:
                        skipped_rows += 1
                        continue

                    currency = (row.get("prices.currency") or "").strip().upper()

                    if currency == "USD":
                        price = price * Decimal("83")

                    date_seen = row.get("prices.dateSeen") or ""
                    first_date = date_seen.split(",")[0].strip()

                    if not first_date:
                        recorded_at = timezone.now()
                    else:
                        try:
                            dt = datetime.fromisoformat(first_date.replace("Z", "+00:00"))
                            recorded_at = timezone.make_aware(dt.replace(tzinfo=None))
                        except Exception:
                            recorded_at = timezone.now()

                    last_record = PriceRecord.objects.filter(product=product).order_by("-recorded_at").first()

                    if last_record:
                        diff = abs(price - last_record.price)
                        if diff > last_record.price * 5:
                            skipped_rows += 1
                            continue

                    PriceRecord.objects.create(
                        product=product,
                        source=source,
                        price=price,
                        raw_price_text=str(price_raw),
                        recorded_at=recorded_at,
                    )

                    created_records += 1

                except Exception:
                    skipped_rows += 1
                    continue

        self.stdout.write(self.style.SUCCESS("✅ Import Completed"))
        self.stdout.write(f"Products created: {created_products}")
        self.stdout.write(f"Price records created: {created_records}")
        self.stdout.write(f"Rows skipped: {skipped_rows}")

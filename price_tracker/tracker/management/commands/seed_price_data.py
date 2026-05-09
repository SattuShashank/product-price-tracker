from decimal import Decimal
from datetime import timedelta, time
import random

from django.core.management.base import BaseCommand
from django.utils import timezone

from tracker.models import MarketplaceSource, Product, PriceRecord


class Command(BaseCommand):
    help = "Seed sample products and daily price history."

    def handle(self, *args, **options):
        self.stdout.write("Command started...")

        source, _ = MarketplaceSource.objects.get_or_create(
            slug="demo-store",
            defaults={
                "name": "Demo Store",
                "base_url": "https://example.com",
                "list_url": "https://example.com/products",
                "config": {
                    "card_selector": ".product-card",
                    "name_selector": ".title",
                    "price_selector": ".price",
                    "link_selector": "a",
                    "external_id_attribute": "data-id",
                    "currency": "INR",
                },
            },
        )

        product, _ = Product.objects.get_or_create(
            source=source,
            external_id="test-product-1",
            defaults={
                "name": "Test Product",
                "brand": "Test",
                "category": "Demo",
                "source_url": "https://example.com/products/test-product-1",
                "currency": "INR",
            },
        )

        product.price_records.all().delete()

        today = timezone.now().date()

        for i in range(5):
            date = today - timedelta(days=i)
            price = Decimal("10000.00") + Decimal(random.randint(-500, 500))

            hour = random.randint(0, 23)
            minute = random.randint(0, 59)

            record_datetime = timezone.make_aware(
                timezone.datetime.combine(date, time(hour, minute))
            )

            PriceRecord.objects.create(
                product=product,
                source=source,
                price=price,
                recorded_at=record_datetime,
            )

        self.stdout.write(self.style.SUCCESS("Test data created successfully"))
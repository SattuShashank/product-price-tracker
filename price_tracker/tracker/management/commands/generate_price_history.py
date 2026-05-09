import random
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from tracker.models import Product, PriceRecord


class Command(BaseCommand):
    help = "Generate synthetic price history for each product"

    def handle(self, *args, **kwargs):
        products = Product.objects.all()

        created = 0

        for product in products:
            base_price = random.randint(1000, 100000)

            for i in range(30):  # 30 days history
                price_variation = random.uniform(-0.1, 0.1)
                price = base_price * (1 + price_variation)

                PriceRecord.objects.create(
                    product=product,
                    source=product.source,
                    price=round(price, 2),
                    recorded_at=timezone.now() - timedelta(days=30 - i)
                )

                created += 1

        self.stdout.write(self.style.SUCCESS(f"✅ Created {created} price records"))
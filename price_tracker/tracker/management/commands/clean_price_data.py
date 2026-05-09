from django.core.management.base import BaseCommand
from tracker.models import PriceRecord

class Command(BaseCommand):
    help = "Clean duplicate price records (same product, same day)"

    def handle(self, *args, **kwargs):
        seen = set()
        deleted = 0

        records = PriceRecord.objects.all().order_by("product_id", "recorded_at")

        for r in records:
            key = (r.product_id, r.recorded_at.date())
            if key in seen:
                r.delete()
                deleted += 1
            else:
                seen.add(key)

        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} duplicate records"))
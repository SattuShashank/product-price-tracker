from django.core.management.base import BaseCommand
from tracker.models import Product
from tracker.scrapers.playwright_scraper import run_scraper


class Command(BaseCommand):
    help = "Collect products until 1000 tracked products exist"

    def handle(self, *args, **options):
        target = 1000

        while True:
            tracked_count = Product.objects.filter(is_tracked=True).count()
            self.stdout.write(f"Tracked products: {tracked_count}")

            if tracked_count >= target:
                self.stdout.write(self.style.SUCCESS(f"Reached {tracked_count} tracked products."))
                break

            result = __import__("asyncio").run(run_scraper())
            self.stdout.write(str(result))

            new_count = Product.objects.filter(is_tracked=True).count()
            if new_count == tracked_count:
                self.stdout.write(self.style.WARNING("No new products were added this round."))
                break
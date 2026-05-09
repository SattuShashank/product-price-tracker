from django.core.management.base import BaseCommand
import asyncio
from tracker.scrapers.playwright_scraper import run_scraper


class Command(BaseCommand):
    help = "Run Playwright scraper"

    def handle(self, *args, **kwargs):
        self.stdout.write("🚀 Starting scraper...")

        asyncio.run(run_scraper())   # ✅ FIXED HERE

        self.stdout.write("✅ Scraping done")
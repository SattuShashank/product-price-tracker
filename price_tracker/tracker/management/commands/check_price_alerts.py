from django.core.management.base import BaseCommand

from tracker.services.alert_service import run_full_pipeline


class Command(BaseCommand):
    help = "Check price alerts and send notification emails"

    def handle(self, *args, **options):
        run_full_pipeline()
        self.stdout.write(self.style.SUCCESS("Price alert check completed."))

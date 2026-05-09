from django.core.management import call_command
from django.db import close_old_connections
from django.utils import timezone

from tracker.models import AlertRule
from tracker.utils import send_price_alert


def run_full_pipeline():
    """
    1. Run scraper
    2. Check alerts
    3. Send emails
    """

    print("🚀 Running scheduled scraper...")

    try:
        call_command("scrape_marketplaces")
    except Exception as e:
        print("❌ Scraper failed:", e)
        return

    print("✅ Scraping done. Checking alerts...")

    close_old_connections()

    alerts = AlertRule.objects.filter(is_active=True, notified=False)

    triggered_count = 0

    for alert in alerts:
        latest = alert.product.price_records.order_by("-recorded_at").first()

        if not latest:
            continue

        if latest.price <= alert.target_price:
            try:
                send_price_alert(
                    alert.email,
                    alert.product,
                    latest.price,
                    alert.target_price,
                )

                alert.notified = True
                alert.last_triggered_at = timezone.now()
                alert.save(update_fields=["notified", "last_triggered_at"])

                triggered_count += 1

            except Exception as e:
                print(f"❌ Email failed for {alert.product.name}:", e)

    print(f"📢 Alerts triggered: {triggered_count}")

    close_old_connections()
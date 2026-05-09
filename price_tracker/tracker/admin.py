from django.contrib import admin
from .models import AlertRule, MarketplaceSource, PriceRecord, Product, ScrapeLog


@admin.register(MarketplaceSource)
class MarketplaceSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "base_url", "is_active")
    list_filter = ("is_active",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "source", "brand", "category", "currency", "last_scraped_at", "is_active")
    list_filter = ("source", "category", "is_active")


@admin.register(PriceRecord)
class PriceRecordAdmin(admin.ModelAdmin):
    list_display = ("product", "source", "price", "recorded_at")
    list_filter = ("source", "recorded_at")


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ("product", "target_price", "is_active", "last_triggered_at")
    list_filter = ("is_active",)


@admin.register(ScrapeLog)
class ScrapeLogAdmin(admin.ModelAdmin):
    list_display = ("source", "status", "http_status_code", "started_at", "finished_at")
    list_filter = ("status", "source")
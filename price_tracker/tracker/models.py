from django.db import models
from django.utils import timezone


class MarketplaceSource(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    base_url = models.URLField()
    list_url = models.URLField(blank=True)
    headers = models.JSONField(default=dict, blank=True)
    config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Product(models.Model):
    source = models.ForeignKey(
        MarketplaceSource,
        on_delete=models.CASCADE,
        related_name="products",
    )
    name = models.CharField(max_length=255)
    brand = models.CharField(max_length=100, blank=True)
    category = models.CharField(max_length=100, blank=True)
    source_url = models.TextField()
    external_id = models.CharField(max_length=500, db_index=True)
    currency = models.CharField(max_length=10, default="INR")
    image_url = models.TextField(blank=True, null=True)
    local_image = models.ImageField(upload_to="product_images/", blank=True, null=True)
    availability = models.CharField(max_length=100, blank=True)
    last_scraped_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_tracked = models.BooleanField(default=False, db_index=True)

    def __str__(self):
        return self.name


class PriceRecord(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="price_records",
    )
    source = models.ForeignKey(
        MarketplaceSource,
        on_delete=models.CASCADE,
        related_name="price_records",
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    raw_price_text = models.CharField(max_length=100, blank=True)
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)

    def __str__(self):
        return f"{self.product.name} - {self.price}"


class ScrapeLog(models.Model):
    STATUS_PENDING = "pending"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
    ]

    source = models.ForeignKey(
        MarketplaceSource,
        on_delete=models.CASCADE,
        related_name="scrape_logs",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scrape_logs",
    )

    requested_url = models.URLField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)

    http_status_code = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    raw_payload = models.JSONField(null=True, blank=True)

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.source.name} - {self.status}"


class AlertRule(models.Model):
    from django.contrib.auth.models import User
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="alerts",
    )
    target_price = models.DecimalField(max_digits=10, decimal_places=2)
    email = models.EmailField(default="test@example.com")
    notified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    last_triggered_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.product.name} <= {self.target_price} ({self.email})"
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.utils import timezone
from django.utils.text import slugify

from tracker.models import MarketplaceSource, PriceRecord, Product, ScrapeLog


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}


def parse_price(text):
    """
    Convert strings like:
    "₹12,499"
    "$199.99"
    "Rs. 2,999.00"

    into Decimal values.
    """
    if not text:
        return None

    cleaned = re.sub(r"[^\d.,-]", "", text).strip()
    if not cleaned:
        return None

    cleaned = cleaned.replace(",", "")

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def extract_text(node):
    if not node:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def get_attr_url(node, base_url, attr_name="href"):
    if not node or not node.has_attr(attr_name):
        return ""
    return urljoin(base_url, node[attr_name])


def extract_external_id(url, card, config):
    """
    Always generate a UNIQUE ID from product URL.
    """
    if url:
        return url.strip().lower()

    return "unknown-product"


def _select_text(card, detail_soup, detail_selector, list_selector):
    """
    Try detail page first, then fall back to listing card.
    """
    if detail_soup and detail_selector:
        node = detail_soup.select_one(detail_selector)
        value = extract_text(node)
        if value:
            return value

    if list_selector:
        node = card.select_one(list_selector)
        value = extract_text(node)
        if value:
            return value

    return ""


def _select_image_url(card, detail_soup, detail_selector, list_selector, base_url, image_attr="src"):
    """
    Try detail page first, then fall back to listing card.
    """
    if detail_soup and detail_selector:
        node = detail_soup.select_one(detail_selector)
        if node and node.has_attr(image_attr):
            return urljoin(base_url, node[image_attr])

    if list_selector:
        node = card.select_one(list_selector)
        if node and node.has_attr(image_attr):
            return urljoin(base_url, node[image_attr])

    return ""


def _get_next_page_url(soup, current_url, config):
    """
    Read the next page link from the page.
    """
    next_selector = config.get("next_page_selector")
    if not next_selector:
        return ""

    next_node = soup.select_one(next_selector)
    if not next_node:
        return ""

    attr_name = config.get("next_page_attribute", "href")
    return get_attr_url(next_node, current_url, attr_name)


def _should_fetch_detail(config):
    """
    If any detail-page selector is provided, we should open the product page.
    """
    return bool(
        config.get("scrape_detail_page")
        or config.get("detail_name_selector")
        or config.get("detail_price_selector")
        or config.get("detail_brand_selector")
        or config.get("detail_category_selector")
        or config.get("detail_availability_selector")
        or config.get("detail_image_selector")
    )


def _resolve_product_url(card, current_page_url, config):
    """
    Find the product page URL.

    Priority:
    1. link_selector from config
    2. first <a href="..."> inside the card
    3. current page URL as fallback
    """
    link_selector = config.get("link_selector")

    link_node = card.select_one(link_selector) if link_selector else None
    if not link_node:
        link_node = card.select_one("a[href]")

    href = ""
    if link_node and link_node.has_attr("href"):
        href = link_node["href"]

    if href:
        return urljoin(current_page_url, href)

    return current_page_url


def scrape_source(source: MarketplaceSource):
    """
    Generic static-page scraper.

    Example config:
    {
      "card_selector": ".product-card",
      "name_selector": ".title",
      "price_selector": ".price",
      "link_selector": "a",
      "image_selector": "img",
      "brand_selector": ".brand",
      "category_selector": ".category",
      "availability_selector": ".stock",
      "external_id_attribute": "data-id",
      "currency": "INR",
      "timeout": 20,
      "max_pages": 50,
      "next_page_selector": "a.next-page",
      "scrape_detail_page": false
    }

    Optional detail-page selectors use the same names with a "detail_" prefix:
    "detail_price_selector", "detail_name_selector", etc.
    """
    if not source.is_active:
        return {"source": source.slug, "status": "skipped", "reason": "inactive"}

    list_url = source.list_url or source.base_url
    config = source.config or {}

    timeout = int(config.get("timeout", 20) or 20)
    max_pages = int(config.get("max_pages", 1) or 1)
    fetch_detail_page = _should_fetch_detail(config)

    log = ScrapeLog.objects.create(
        source=source,
        requested_url=list_url,
        status=ScrapeLog.STATUS_PENDING,
    )

    session = requests.Session()
    headers = DEFAULT_HEADERS.copy()
    headers.update(source.headers or {})

    stats = {
        "items_found": 0,
        "pages_scraped": 0,
        "products_created": 0,
        "products_seen": 0,
        "price_records_created": 0,
        "products_updated": 0,
        "products_skipped": 0,
    }

    last_status_code = None

    try:
        next_url = list_url
        visited_urls = set()

        while next_url and stats["pages_scraped"] < max_pages and next_url not in visited_urls:
            visited_urls.add(next_url)

            response = session.get(next_url, headers=headers, timeout=timeout)
            last_status_code = response.status_code
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "lxml")

            card_selector = config.get("card_selector")
            if not card_selector:
                raise ValueError(f"Missing card_selector in config for source: {source.slug}")

            cards = soup.select(card_selector)
            stats["items_found"] += len(cards)

            for card in cards:
                product_url = _resolve_product_url(card, next_url, config)

                detail_soup = None
                if fetch_detail_page and product_url:
                    try:
                        detail_resp = session.get(product_url, headers=headers, timeout=timeout)
                        detail_resp.raise_for_status()
                        detail_soup = BeautifulSoup(detail_resp.text, "lxml")
                    except requests.RequestException:
                        detail_soup = None

                name = _select_text(
                    card,
                    detail_soup,
                    config.get("detail_name_selector"),
                    config.get("name_selector"),
                )
                if not name:
                    stats["products_skipped"] += 1
                    continue

                price_text = _select_text(
                    card,
                    detail_soup,
                    config.get("detail_price_selector"),
                    config.get("price_selector"),
                )
                price = parse_price(price_text)

                brand = _select_text(
                    card,
                    detail_soup,
                    config.get("detail_brand_selector"),
                    config.get("brand_selector"),
                )
                category = _select_text(
                    card,
                    detail_soup,
                    config.get("detail_category_selector"),
                    config.get("category_selector"),
                )
                availability = _select_text(
                    card,
                    detail_soup,
                    config.get("detail_availability_selector"),
                    config.get("availability_selector"),
                )

                image_url = _select_image_url(
                    card,
                    detail_soup,
                    config.get("detail_image_selector"),
                    config.get("image_selector"),
                    next_url,
                    image_attr=config.get("image_attribute", "src"),
                )

                external_id = extract_external_id(product_url, card, config)

                product, created = Product.objects.update_or_create(
                    source=source,
                    external_id=external_id,
                    defaults={
                        "name": name[:500],
                        "brand": brand[:100],
                        "category": category[:100],
                        "source_url": product_url,
                        "currency": config.get("currency", "INR"),
                        "image_url": image_url,
                        "availability": availability[:100],
                        "last_scraped_at": timezone.now(),
                        "is_active": True,
                        "is_tracked": True,
                    },
                )

                stats["products_seen"] += 1
                if created:
                    stats["products_created"] += 1
                else:
                    stats["products_updated"] += 1

                if price is not None:
                    today = timezone.localdate()
                    already_saved_today = product.price_records.filter(recorded_at__date=today).exists()

                    if not already_saved_today:
                        PriceRecord.objects.create(
                            product=product,
                            source=source,
                            price=price,
                            raw_price_text=price_text[:100],
                        )
                        stats["price_records_created"] += 1
                else:
                    stats["products_skipped"] += 1

            next_url = _get_next_page_url(soup, next_url, config)

        log.status = ScrapeLog.STATUS_SUCCESS
        log.http_status_code = last_status_code or 200
        log.raw_payload = stats
        log.finished_at = timezone.now()
        log.save(update_fields=["status", "http_status_code", "raw_payload", "finished_at"])

        return {
            "source": source.slug,
            "status": "success",
            **stats,
        }

    except Exception as exc:
        log.status = ScrapeLog.STATUS_FAILED
        log.error_message = str(exc)
        log.finished_at = timezone.now()
        log.save(update_fields=["status", "error_message", "finished_at"])

        return {
            "source": source.slug,
            "status": "failed",
            "error": str(exc),
            **stats,
        }
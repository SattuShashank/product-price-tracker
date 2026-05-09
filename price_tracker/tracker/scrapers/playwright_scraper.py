import asyncio
import hashlib
import mimetypes
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlparse

import requests
from asgiref.sync import sync_to_async
from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.text import slugify
from playwright.async_api import async_playwright

from tracker.scrape_config import SCRAPE_TARGETS


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def parse_price(text: str):
    if not text:
        return None

    cleaned = str(text).replace("\xa0", " ").strip()
    match = re.search(r"(\d[\d,]*\.?\d*)", cleaned)
    if not match:
        return None

    number = match.group(1).replace(",", "")
    try:
        return Decimal(number)
    except (InvalidOperation, ValueError):
        return None


def _normalize_url(url, base_url):
    if not url:
        return ""
    return urljoin(base_url, url)


def _pick_from_srcset(srcset: str):
    if not srcset:
        return ""

    parts = [part.strip() for part in srcset.split(",") if part.strip()]
    for part in parts:
        url = part.split()[0].strip()
        if url and not url.startswith("data:"):
            return url
    return ""


async def _extract_image_url(element, base_url: str):
    if not element:
        return ""

    for attr in ("data-src", "data-original", "data-lazy-src", "src"):
        value = await element.get_attribute(attr)   # ✅ FIX
        if value and not value.startswith("data:"):
            return _normalize_url(value, base_url)

    for attr in ("srcset", "data-srcset"):
        value = await element.get_attribute(attr)   # ✅ FIX
        candidate = _pick_from_srcset(value)
        if candidate:
            return _normalize_url(candidate, base_url)

    return ""


async def _extract_link_url(element, base_url: str):
    if not element:
        return ""

    href = await element.get_attribute("href")  # ✅ FIX
    return _normalize_url(href, base_url)


def _source_defaults(target):
    site = target["site"].strip().lower()
    return {
        "name": target.get("name") or site.title(),
        "slug": site,
        "base_url": target["url"],
        "list_url": target["url"],
        "config": {
            "site": site,
        },
    }


def _product_fingerprint(source_slug: str, product_url: str, title: str):
    raw = product_url or f"{source_slug}::{title}"
    return hashlib.sha1(raw.strip().lower().encode("utf-8")).hexdigest()


def download_image_bytes(image_url: str, referer: str = "", user_agent: str = DEFAULT_USER_AGENT):
    if not image_url or not image_url.startswith("http"):
        return None

    try:
        headers = {
            "User-Agent": user_agent,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        if referer:
            headers["Referer"] = referer

        response = requests.get(image_url, headers=headers, timeout=20)
        if response.status_code != 200 or not response.content:
            return None

        content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
        ext = mimetypes.guess_extension(content_type) if content_type else None
        if not ext:
            parsed_path = urlparse(image_url).path.lower()
            ext = ".png" if parsed_path.endswith(".png") else ".jpg"

        return response.content, ext
    except Exception as exc:
        print("❌ Image download error:", exc)
        return None


def save_product_sync(title, price, target, image_url=None, product_url=None, raw_price_text=""):
    from tracker.models import MarketplaceSource, PriceRecord, Product

    source_obj, _ = MarketplaceSource.objects.get_or_create(
        slug=target["site"].strip().lower(),
        defaults=_source_defaults(target),
    )

    external_id = _product_fingerprint(source_obj.slug, product_url, title)

    product, _ = Product.objects.get_or_create(
        source=source_obj,
        external_id=external_id,
        defaults={
            "name": title[:255],
            "brand": "",
            "category": target.get("category", "")[:100],
            "source_url": product_url or target["url"],
            "currency": "INR",
            "image_url": image_url or "",
            "availability": "",
            "last_scraped_at": timezone.now(),
            "is_active": True,
            "is_tracked":True,
        },
    )

    product.name = title[:255]
    product.category = target.get("category", product.category or "")[:100]
    product.source_url = product_url or product.source_url or target["url"]
    product.currency = "INR"
    product.last_scraped_at = timezone.now()
    product.is_active = True

    updated_fields = [
        "name",
        "category",
        "source_url",
        "currency",
        "last_scraped_at",
        "is_active",
    ]

    if image_url and image_url.startswith("http"):
        if product.image_url != image_url:
            product.image_url = image_url
            updated_fields.append("image_url")

        needs_local_image = (not product.local_image) or (product.image_url != image_url)
        if needs_local_image:
            downloaded = download_image_bytes(image_url, referer=product.source_url)
            if downloaded:
                data, ext = downloaded
                filename = (
                    f"{slugify(title)[:60] or 'product'}_"
                    f"{hashlib.md5(image_url.encode('utf-8')).hexdigest()[:10]}"
                    f"{ext}"
                )
                product.local_image.save(filename, ContentFile(data), save=False)
                updated_fields.append("local_image")
                print("✅ Image saved:", filename)
            else:
                print("❌ Failed to download:", image_url)

    product.save(update_fields=list(dict.fromkeys(updated_fields)))

    today = timezone.localdate()
    already_saved_today = PriceRecord.objects.filter(
        product=product,
        recorded_at__date=today
    ).exists()

    if not already_saved_today:
        PriceRecord.objects.create(
            product=product,
            source=source_obj,
            price=price,
            raw_price_text=(raw_price_text or "")[:100],
            recorded_at=timezone.now(),
        ) 


save_product = sync_to_async(save_product_sync, thread_sensitive=True)


async def extract_amazon_product(item, base_url):
    title = ""
    title_el = await item.query_selector("h2 a span")
    if title_el:
        title = (await title_el.inner_text()).strip()

    if not title:
        alt_title_el = await item.query_selector("h2")
        if alt_title_el:
            title = (await alt_title_el.inner_text()).strip()

    price_text = ""
    price_el = await item.query_selector(".a-price .a-offscreen")
    if price_el:
        price_text = (await price_el.inner_text()).strip()

    if not price_text:
        whole_el = await item.query_selector(".a-price-whole")
        fraction_el = await item.query_selector(".a-price-fraction")
        whole = (await whole_el.inner_text()).strip().replace(",", "") if whole_el else ""
        fraction = (await fraction_el.inner_text()).strip() if fraction_el else "00"
        if whole:
            price_text = f"{whole}.{fraction or '00'}"

    image_url = ""
    image_el = await item.query_selector("img.s-image")
    if image_el:
        image_url = await _extract_image_url(image_el, base_url)

    product_url = ""
    link_el = await item.query_selector("h2 a[href]")
    if link_el:
        product_url = await _extract_link_url(link_el, base_url)

    if not title or not price_text:
        return None

    return {
        "title": title,
        "price_text": price_text,
        "price": parse_price(price_text),
        "image_url": image_url,
        "product_url": product_url,
    }


async def extract_flipkart_product(item, base_url):
    title = ""
    for selector in ("div.KzDlHZ", "a.wjcEIp", "a.s1Q9rs", "div._4rR01T", "span.B_NuCI"):
        node = await item.query_selector(selector)
        if node:
            title = (await node.inner_text()).strip()
            if title:
                break

    price_text = ""
    for selector in ("div._30jeq3", "div.Nx9bqj"):
        node = await item.query_selector(selector)
        if node:
            price_text = (await node.inner_text()).strip()
            if price_text:
                break

    image_url = ""
    image_el = await item.query_selector("img")
    if image_el:
        image_url = await _extract_image_url(image_el, base_url)

    product_url = ""
    link_el = await item.query_selector("a[href]")
    if link_el:
        product_url =await _extract_link_url(link_el, base_url)

    if not title or not price_text:
        return None

    return {
        "title": title,
        "price_text": price_text,
        "price": parse_price(price_text),
        "image_url": image_url,
        "product_url": product_url,
    }


async def run_scraper():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        context = await browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            viewport={"width": 1400, "height": 1800},
        )

        total_saved = 0

        for target in SCRAPE_TARGETS:
            print(f"\n🔎 Scraping: {target['name']}")

            for page_num in range(1, 51):
                print(f"📄 Page: {page_num}")

                page = await context.new_page()

                try:
                    url = target["url"] + f"&page={page_num}"
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(3000)

                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(2000)

                    site = target["site"].lower()

                    if site == "amazon":
                        items = await page.query_selector_all(
                            "div.s-result-item[data-component-type='s-search-result']"
                        )
                        print("🟡 Amazon products:", len(items))

                        for item in items:
                            try:
                                data = await extract_amazon_product(item, url)
                                if not data or not data["price"]:
                                    continue

                                if data["price"] > 500000:
                                    continue

                                await save_product(
                                    data["title"],
                                    data["price"],
                                    target,
                                    data["image_url"],
                                    data["product_url"],
                                    data["price_text"],
                                )
                                total_saved += 1
                            except Exception as exc:
                                print("Amazon error:", exc)

                    elif site == "flipkart":
                        items = await page.query_selector_all(
                            "div._1AtVbE, div[data-id], div.slAVV4"
                        )
                        print("🟡 Flipkart products:", len(items))

                        for item in items:
                            try:
                                data = await extract_flipkart_product(item, url)
                                if not data or not data["price"]:
                                    continue

                                if data["price"] > 500000:
                                    continue

                                await save_product(
                                    data["title"],
                                    data["price"],
                                    target,
                                    data["image_url"],
                                    data["product_url"],
                                    data["price_text"],
                                )
                                total_saved += 1
                            except Exception as exc:
                                print("Flipkart error:", exc)

                except Exception as exc:
                    print("Page error:", exc)

                finally:
                    await page.close()

        await browser.close()
        return {"status": "success", "saved": total_saved}


if __name__ == "__main__":
    asyncio.run(run_scraper())
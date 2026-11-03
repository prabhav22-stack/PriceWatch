"""Personal Portfolio Export and Google Sheets Synchronization Service.

Enables users to export tracked products, price drop records, and total savings
into downloadable CSV documents or directly sync to personal Google Sheets.
"""

import csv
import io
from dataclasses import dataclass
from typing import List, Optional

from pricewatch.domain.models import CanonicalListing, Subscription
from pricewatch.logging_setup import get_logger
from pricewatch.validation.normalizer import format_paise_to_inr

logger = get_logger("export_service")


@dataclass
class ExportRecord:
    product_title: str
    store_name: str
    current_price_str: str
    target_price_str: str
    status: str
    url: str


class ExportService:
    """Generates portfolio CSV sheets and handles Google Sheets integration."""

    def build_csv_document(self, listings_and_subs: List[tuple]) -> bytes:
        """Formats active user subscriptions into standard CSV document bytes."""
        output = io.StringIO()
        writer = csv.writer(output)

        # Header row
        writer.writerow([
            "Product Name",
            "Store Provider",
            "Current Price (INR)",
            "Target Alert Price (INR)",
            "Stock Status",
            "Store Link",
        ])

        for item in listings_and_subs:
            if isinstance(item[0], CanonicalListing):
                listing = item[0]
                sub = item[1]
            else:
                sub = item[0]
                listing = item[1]

            curr_price = format_paise_to_inr(listing.last_price_paise) if listing.last_price_paise else "N/A"
            target_price = format_paise_to_inr(sub.target_price_paise) if sub.target_price_paise else "Any Price Drop"
            stock = "In Stock" if listing.last_available else "Out of Stock"
            url = listing.canonical_url or ""

            writer.writerow([
                listing.product_title,
                listing.provider_code.title(),
                curr_price,
                target_price,
                stock,
                url,
            ])

        output.seek(0)
        return output.getvalue().encode("utf-8")

    async def sync_with_google_sheet(
        self,
        spreadsheet_key_or_url: str,
        listings_and_subs: List[tuple],
        credentials_json: Optional[str] = None,
    ) -> bool:
        """Synchronizes tracked items to a user's Google Sheet via gspread."""
        try:
            import gspread
            if credentials_json:
                gc = gspread.service_account(filename=credentials_json)
            else:
                gc = gspread.service_account()

            sh = gc.open_by_key(spreadsheet_key_or_url) if not spreadsheet_key_or_url.startswith("http") else gc.open_by_url(spreadsheet_key_or_url)
            worksheet = sh.sheet1

            rows = [
                ["Product Name", "Store", "Current Price", "Target Price", "Stock", "URL"]
            ]
            for item in listings_and_subs:
                if isinstance(item[0], CanonicalListing):
                    listing = item[0]
                    sub = item[1]
                else:
                    sub = item[0]
                    listing = item[1]
                curr = format_paise_to_inr(listing.last_price_paise) if listing.last_price_paise else "N/A"
                tgt = format_paise_to_inr(sub.target_price_paise) if sub.target_price_paise else "Any Drop"
                stock = "In Stock" if listing.last_available else "Out of Stock"
                rows.append([listing.product_title, listing.provider_code.title(), curr, tgt, stock, listing.canonical_url])

            worksheet.clear()
            worksheet.update("A1", rows)
            return True
        except Exception as exc:
            logger.debug("Google Sheets sync exception", error=str(exc))
            return False


export_service = ExportService()

"""Service for tracking and persisting Amul product stock history.

Replicates the ProductStockHistory tracking logic from upstream amul-notify:
- last_seen_in_stock_at: Updated whenever product is observed available
- first_seen_in_stock_at: Set when product transitions from OOS to In-Stock
- last_seen_out_of_stock_at: Set when product transitions from In-Stock to OOS
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pricewatch.config import Settings
from pricewatch.logging_setup import get_logger

logger = get_logger("amul_stock_tracker")


class AmulStockHistoryItem:
    def __init__(
        self,
        sku: str,
        substore: str,
        last_seen_in_stock_at: Optional[datetime] = None,
        first_seen_in_stock_at: Optional[datetime] = None,
        last_seen_out_of_stock_at: Optional[datetime] = None,
    ):
        self.sku = sku
        self.substore = substore
        self.last_seen_in_stock_at = last_seen_in_stock_at
        self.first_seen_in_stock_at = first_seen_in_stock_at
        self.last_seen_out_of_stock_at = last_seen_out_of_stock_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sku": self.sku,
            "substore": self.substore,
            "last_seen_in_stock_at": self.last_seen_in_stock_at.isoformat() if self.last_seen_in_stock_at else None,
            "first_seen_in_stock_at": self.first_seen_in_stock_at.isoformat() if self.first_seen_in_stock_at else None,
            "last_seen_out_of_stock_at": self.last_seen_out_of_stock_at.isoformat() if self.last_seen_out_of_stock_at else None,
        }


class AmulStockTracker:
    _instance: Optional["AmulStockTracker"] = None

    def __init__(self, supabase_client: Optional[Any] = None):
        self._cache: Dict[Tuple[str, str], AmulStockHistoryItem] = {}
        self._client = supabase_client
        if not self._client:
            settings = Settings()
            if settings.SUPABASE_URL and (settings.SUPABASE_KEY or settings.SUPABASE_ACCESS_TOKEN):
                try:
                    from supabase import create_client
                    key = settings.SUPABASE_KEY or settings.SUPABASE_ACCESS_TOKEN
                    self._client = create_client(settings.SUPABASE_URL, key)
                except Exception as e:
                    logger.warning("Could not initialize Supabase client in AmulStockTracker", error=str(e))

    @classmethod
    def get_instance(cls, supabase_client: Optional[Any] = None) -> "AmulStockTracker":
        if cls._instance is None:
            cls._instance = AmulStockTracker(supabase_client=supabase_client)
        elif supabase_client is not None:
            cls._instance._client = supabase_client
        return cls._instance

    def get_history(self, sku: str, substore: str) -> Optional[AmulStockHistoryItem]:
        """Retrieve stock history from memory cache."""
        key = (sku, substore)
        return self._cache.get(key)

    async def load_history_for_substore(self, substore: str) -> None:
        """Prefetch all stock history records for a substore from Supabase."""
        if not self._client:
            return
        try:
            res = (
                self._client.table("amul_stock_history")
                .select("sku, substore, last_seen_in_stock_at, first_seen_in_stock_at, last_seen_out_of_stock_at")
                .eq("substore", substore)
                .execute()
            )
            for row in (res.data or []):
                sku = row["sku"]
                last_in = datetime.fromisoformat(row["last_seen_in_stock_at"]) if row.get("last_seen_in_stock_at") else None
                first_in = datetime.fromisoformat(row["first_seen_in_stock_at"]) if row.get("first_seen_in_stock_at") else None
                last_out = datetime.fromisoformat(row["last_seen_out_of_stock_at"]) if row.get("last_seen_out_of_stock_at") else None
                self._cache[(sku, substore)] = AmulStockHistoryItem(
                    sku=sku,
                    substore=substore,
                    last_seen_in_stock_at=last_in,
                    first_seen_in_stock_at=first_in,
                    last_seen_out_of_stock_at=last_out,
                )
        except Exception as exc:
            logger.warning("Failed to prefetch Amul stock history from Supabase", error=str(exc))

    def record_observation(
        self,
        sku: str,
        substore: str,
        is_available: bool,
        observed_at: Optional[datetime] = None,
    ) -> AmulStockHistoryItem:
        """
        Record a stock observation for (sku, substore), updating transitions in memory
        and queuing Supabase persistence.
        """
        now = observed_at or datetime.now(timezone.utc)
        key = (sku, substore)
        item = self._cache.get(key)

        if not item:
            item = AmulStockHistoryItem(
                sku=sku,
                substore=substore,
                last_seen_in_stock_at=now if is_available else None,
                first_seen_in_stock_at=now if is_available else None,
                last_seen_out_of_stock_at=now if not is_available else None,
            )
            self._cache[key] = item
        else:
            was_available = (
                item.last_seen_in_stock_at is not None
                and (item.last_seen_out_of_stock_at is None or item.last_seen_in_stock_at >= item.last_seen_out_of_stock_at)
            )

            if is_available:
                item.last_seen_in_stock_at = now
                if not was_available or item.first_seen_in_stock_at is None:
                    # Transitioned from OOS to In-Stock
                    item.first_seen_in_stock_at = now
            else:
                if was_available or item.last_seen_out_of_stock_at is None:
                    # Transitioned from In-Stock to OOS
                    item.last_seen_out_of_stock_at = now

        # Fire async / non-blocking persist to Supabase if client is ready
        if self._client:
            try:
                payload = {
                    "sku": sku,
                    "substore": substore,
                    "last_seen_in_stock_at": item.last_seen_in_stock_at.isoformat() if item.last_seen_in_stock_at else None,
                    "first_seen_in_stock_at": item.first_seen_in_stock_at.isoformat() if item.first_seen_in_stock_at else None,
                    "last_seen_out_of_stock_at": item.last_seen_out_of_stock_at.isoformat() if item.last_seen_out_of_stock_at else None,
                    "updated_at": now.isoformat(),
                }
                self._client.table("amul_stock_history").upsert(
                    payload, on_conflict="sku,substore"
                ).execute()
            except Exception as exc:
                logger.warning("Failed to persist amul_stock_history upsert", sku=sku, error=str(exc))

        return item

    def record_batch_observations(
        self,
        products: List[Dict[str, Any]],
        substore: str,
    ) -> None:
        """Update stock histories for a list of products fetched from StoreHippo."""
        now = datetime.now(timezone.utc)
        for p in products:
            sku = p.get("sku")
            if not sku:
                continue
            is_avail = bool(p.get("available", False))
            self.record_observation(sku=sku, substore=substore, is_available=is_avail, observed_at=now)

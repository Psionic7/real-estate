"""Stable apartment identities and summaries for the browser-scoped watchlist."""
import json

import pandas as pd

from estate.analytics import APARTMENT_KEYS, apartment_sample, apartment_stats, monthly_stats


def apartment_id(item):
    """Return a portable identity for an apartment without relying on coordinates."""
    return json.dumps([str(item.get(key, "")) for key in APARTMENT_KEYS],
                      ensure_ascii=False, separators=(",", ":"))


def apartment_identity(value):
    try:
        parts = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(parts, list) or len(parts) != len(APARTMENT_KEYS):
        return None
    return dict(zip(APARTMENT_KEYS, map(str, parts)))


def parse_favorites(raw, limit=20):
    try:
        values = json.loads(raw or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(values, list):
        return []
    valid = []
    for value in values:
        if isinstance(value, str) and apartment_identity(value) and value not in valid:
            valid.append(value)
    return valid[:limit]


def filter_favorites(frame, favorite_ids):
    if frame.empty or not favorite_ids:
        return frame.iloc[0:0].copy()
    mask = pd.Series(False, index=frame.index)
    for value in favorite_ids:
        identity = apartment_identity(value)
        if identity:
            current = pd.Series(True, index=frame.index)
            for key, expected in identity.items():
                current &= frame[key].astype(str) == expected
            mask |= current
    return frame[mask].copy()


def watchlist_summary(trades, listings, favorite_ids):
    """Build one dashboard row per favorite that has a matching transaction."""
    rows = []
    for value in favorite_ids:
        identity = apartment_identity(value)
        if not identity:
            continue
        sample = apartment_sample(trades, identity)
        active = apartment_sample(listings, identity) if not listings.empty else listings.copy()
        if sample.empty:
            rows.append({**identity, "favorite_id": value, "count": 0, "median_price": None,
                         "latest_date": None, "latest_price": None, "change_3m": None,
                         "listing_count": len(active),
                         "listing_median": active["price_eok"].median() if len(active) else None})
            continue
        summary = apartment_stats(sample).iloc[0].to_dict()
        monthly = monthly_stats(sample)
        change = None
        if len(monthly) >= 2:
            recent = monthly.tail(3)["중위가격(억원)"].median()
            previous = monthly.iloc[-6:-3]["중위가격(억원)"].median()
            if pd.notna(previous) and previous:
                change = (recent / previous - 1) * 100
        rows.append({**summary, "favorite_id": value, "change_3m": change,
                     "listing_count": len(active),
                     "listing_median": active["price_eok"].median() if len(active) else None})
    return pd.DataFrame(rows)

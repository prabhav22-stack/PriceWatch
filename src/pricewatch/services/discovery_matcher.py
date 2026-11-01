"""Product title, variant spec, and semantic matcher for cross-store discovery."""

import re
from typing import Optional, Tuple
from rapidfuzz import fuzz


# Common supplement brands
KNOWN_BRANDS = [
    "nutrabay",
    "muscleblaze",
    "koshaveda",
    "nakpro",
    "asitis",
    "as-it-is",
    "atom",
    "yogabar",
    "kapiva",
    "fuelone",
    "gnc",
    "myprotein",
    "optimum nutrition",
    "on",
    "carbamide forte",
    "rasayanam",
    "truhabit",
    "himalaya",
    "bepure",
    "fast&up",
    "amul",
    "appleveda",
    "upakarma",
    "dabur",
    "wellcore",
]

# Marketing buzzwords to filter for clean comparison
NOISE_WORDS = {
    "100%", "pure", "natural", "original", "authentic", "premium", "best",
    "clinically", "tested", "proven", "certified", "ayurvedic", "himalayan",
    "supplement", "high", "quality", "for", "men", "women", "adults",
    "organic", "grade", "gold", "super", "daily", "boost", "booster",
    "with", "and", "pro", "advanced", "ultra", "extra", "strength",
}

# Core supplement categories to guard against false cross-category substitutions
CORE_PRODUCT_CATEGORIES = {
    "shilajit", "whey", "isolate", "concentrate", "creatine", "casein",
    "peanut", "butter", "multivitamin", "fish", "oil", "omega",
    "ashwagandha", "glutamine", "bcaa", "eaa", "collagen",
    "magnesium", "zinc", "zma", "citrulline", "arginine", "gainer",
    "preworkout", "testosterone", "melatonin", "biotin", "electrolyte",
    "bar", "cookie", "lassi", "shake", "milkshake", "paneer",
    "buttermilk", "vinegar", "thistle", "glucosamine", "carnitine",
}


def extract_core_categories(text: str) -> set:
    """Extract known core supplement product categories present in text."""
    if not text:
        return set()
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    words = set(cleaned.split())
    found = words.intersection(CORE_PRODUCT_CATEGORIES)
    # Special multi-word categories
    if "peanut" in words or "butter" in words:
        found.add("peanut_butter")
    if "fish" in words or "omega" in words:
        found.add("omega_fish_oil")
    return found


def extract_weight_in_grams(text: str) -> Optional[int]:
    """Extract and normalize weight/mass from product string into integer grams."""
    if not text:
        return None
    s = text.lower()

    # 1. KG pattern: e.g. 1 kg, 1.5kg, 2 kg, 0.5 kg
    kg_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|kilos?|kilograms?)\b", s)
    if kg_match:
        try:
            return int(round(float(kg_match.group(1)) * 1000))
        except (ValueError, TypeError):
            pass

    # 2. Strip nutritional metrics like "26g protein", "5.3g bcaa", "3g creatine"
    clean_s = re.sub(
        r"\b\d+(?:\.\d+)?\s*(?:g|gm|gms|grams?)\s*(?:protein|bcaa|eaa|creatine|sugar|fat|carbs?|dietary|fiber|glutamine)\b",
        " ",
        s,
    )

    # 3. Grams pattern: e.g. 20 g, 20g, 500 gm, 250gms, 1000 grams
    g_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|gm|gms|grams?)\b", clean_s)
    if g_match:
        try:
            val = float(g_match.group(1))
            # sanity check: 1g to 25000g
            if 1 <= val <= 25000:
                return int(round(val))
        except (ValueError, TypeError):
            pass

    # 4. LBS pattern: e.g. 2.2 lbs, 2.2 lb, 1 lb, 4.4lbs
    lb_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:lbs?|pounds?)\b", clean_s)
    if lb_match:
        try:
            return int(round(float(lb_match.group(1)) * 453.592))
        except (ValueError, TypeError):
            pass

    # 5. Count/Capsules pattern if weight isn't specified: e.g. 60 tabs, 90 capsules
    cnt_match = re.search(r"(\d+)\s*(?:tabs?|tablets?|caps?|capsules?|veg\s*caps?)\b", clean_s)
    if cnt_match:
        try:
            return int(cnt_match.group(1))
        except (ValueError, TypeError):
            pass

    return None


def extract_brand(text: str) -> Optional[str]:
    """Detect known brand from product name."""
    if not text:
        return None
    low = text.lower()
    for brand in KNOWN_BRANDS:
        if re.search(rf"\b{re.escape(brand)}\b", low):
            return brand
    return None


def clean_product_tokens(text: str) -> str:
    """Strip punctuation and marketing buzzwords to keep core identity terms."""
    if not text:
        return ""
    # Normalize punctuation to spaces
    s = re.sub(r"[^\w\s]", " ", text.lower())
    tokens = [w for w in s.split() if w not in NOISE_WORDS and len(w) > 1]
    return " ".join(tokens)


def compute_match_score(
    query_title: str,
    candidate_title: str,
    target_weight_g: Optional[int] = None,
    candidate_weight_g: Optional[int] = None,
    query_brand: Optional[str] = None,
    candidate_brand: Optional[str] = None,
) -> Tuple[float, bool]:
    """Compute semantic match score (0.0 to 1.0) and whether specs are compatible.
    
    Returns:
        (score, is_compatible)
    """
    clean_q = clean_product_tokens(query_title)
    clean_c = clean_product_tokens(candidate_title)

    # 1. Brand compatibility check
    q_b = query_brand or extract_brand(query_title)
    c_b = candidate_brand or extract_brand(candidate_title)

    brand_bonus = 0.0
    if q_b:
        # If query explicitly targets a brand, candidate must match that brand
        has_query_brand = (
            (c_b and (c_b == q_b or (q_b in ("asitis", "as-it-is", "atom") and c_b in ("asitis", "as-it-is", "atom"))))
            or (q_b in candidate_title.lower())
        )
        if not has_query_brand:
            return 0.2, False
        brand_bonus = 0.15
    elif c_b:
        brand_bonus = 0.05

    # 2. Category Guard: prevent cross-category false matches (e.g. Shilajit matching Zinc/Magnesium)
    q_cats = extract_core_categories(query_title)
    c_cats = extract_core_categories(candidate_title)
    if q_cats:
        # If query specified categories, candidate must match at least one
        has_cat_match = bool(q_cats.intersection(c_cats))
        # If not matching and candidate belongs to a completely different supplement category, reject immediately
        if not has_cat_match:
            return 0.10, False

    # 3. Non-Brand Token Coverage Check
    clean_q_list = clean_q.split()
    brand_tokens = set(q_b.split()) if q_b else set()
    q_clean_tokens = [w for w in clean_q_list if w not in brand_tokens]

    c_clean_tokens = set(clean_c.split())
    matched_count = 0
    if q_clean_tokens:
        for tok in q_clean_tokens:
            if tok in c_clean_tokens or any(fuzz.ratio(tok, c_tok) >= 85 for c_tok in c_clean_tokens):
                matched_count += 1
        coverage = matched_count / len(q_clean_tokens)
        if len(q_clean_tokens) == 1 and matched_count == 0:
            return 0.10, False
        if coverage < 0.50:
            return 0.15, False
    else:
        coverage = 1.0

    # 4. Balanced multi-metric base score
    set_ratio = fuzz.token_set_ratio(clean_q, clean_c) / 100.0
    sort_ratio = fuzz.token_sort_ratio(clean_q, clean_c) / 100.0
    base_ratio = 0.40 * set_ratio + 0.35 * sort_ratio + 0.25 * coverage

    # 5. Spec / Weight compatibility check
    spec_penalty = 0.0
    is_spec_compatible = True

    t_w = target_weight_g or extract_weight_in_grams(query_title)
    c_w = candidate_weight_g or extract_weight_in_grams(candidate_title)

    if t_w and c_w:
        ratio = min(t_w, c_w) / max(t_w, c_w)
        if ratio >= 0.90:
            # Exact or near-exact match (e.g. 1000g vs 1kg)
            brand_bonus += 0.10
        else:
            # Incompatible pack size (e.g. 20g vs 50g, or 500g vs 1kg)
            spec_penalty = 0.40
            is_spec_compatible = False

    final_score = min(1.0, max(0.0, base_ratio + brand_bonus - spec_penalty))
    is_valid_match = final_score >= 0.65 and is_spec_compatible
    return final_score, is_valid_match

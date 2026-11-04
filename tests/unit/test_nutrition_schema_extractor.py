"""Unit tests for extruct JSON-LD and microdata nutrition facts extraction."""

import pytest
from pricewatch.services.nutrition_schema_extractor import schema_extractor


SAMPLE_JSON_LD_HTML = """
<!DOCTYPE html>
<html>
<head>
<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "Product",
  "name": "AS-IT-IS Nutrition Whey Protein Concentrate 80% Unflavoured",
  "brand": {
    "@type": "Brand",
    "name": "AS-IT-IS"
  },
  "url": "https://asitisnutrition.com/products/best-whey-protein-concentrate-in-india",
  "offers": {
    "@type": "Offer",
    "price": "3134.00",
    "priceCurrency": "INR",
    "availability": "https://schema.org/InStock"
  },
  "nutrition": {
    "@type": "NutritionInformation",
    "servingSize": "30g",
    "proteinContent": "24g"
  }
}
</script>
</head>
<body>
<h1>Product Page</h1>
</body>
</html>
"""


def test_schema_extractor_parses_json_ld_nutrition():
    info = schema_extractor.extract_from_html(SAMPLE_JSON_LD_HTML, base_url="https://asitisnutrition.com")
    assert info is not None
    assert "AS-IT-IS" in info.product_name
    assert info.brand == "AS-IT-IS"
    assert info.serving_size_g == 30.0
    assert info.protein_content_g == 24.0
    # 24g / 30g = 80.0%
    assert info.protein_percentage == 80.0
    assert info.in_stock is True
    assert info.price == 3134.00
    assert info.canonical_url == "https://asitisnutrition.com/products/best-whey-protein-concentrate-in-india"


def test_schema_extractor_handles_empty_html():
    assert schema_extractor.extract_from_html("") is None
    assert schema_extractor.extract_from_html("<html><body>No schema here</body></html>") is None

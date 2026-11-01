"""Unit tests for Series Guard, Bundle/Combo Guard, and Flavour Guard."""

from pricewatch.services.discovery_matcher import compute_match_score


def test_series_guard_prevents_sub_brand_substitution():
    """Verify that requesting Nakpro Perform does not match Nakpro Impact or Platinum."""
    q = "Nakpro Perform 1kg Unflavoured"
    
    # Impact should be rejected
    c_impact = "Nakpro Impact Whey Protein 1kg Unflavoured"
    score, ok = compute_match_score(q, c_impact, target_weight_g=1000, candidate_weight_g=1000)
    assert not ok
    assert score <= 0.20

    # Platinum should be rejected
    c_platinum = "Nakpro Platinum Whey Protein Isolate 1kg Unflavoured"
    score, ok = compute_match_score(q, c_platinum, target_weight_g=1000, candidate_weight_g=1000)
    assert not ok
    assert score <= 0.20

    # Perform should be accepted
    c_perform = "NAKPRO NUTRITION Perform Whey Protein Concentrate | 1kg Unflavoured"
    score, ok = compute_match_score(q, c_perform, target_weight_g=1000, candidate_weight_g=1000)
    assert ok
    assert score >= 0.85


def test_combo_guard_rejects_unsolicited_bundles():
    """Verify that searching for standalone whey rejects +Creatine and +Shaker combos."""
    q = "Nakpro Perform 1kg Unflavoured"

    c_combo_creatine = "Nakpro Perform Whey Protein 1kg with Creatine Unflavoured 100g"
    score, ok = compute_match_score(q, c_combo_creatine, target_weight_g=1000, candidate_weight_g=1000)
    assert not ok
    assert score <= 0.20

    c_combo_shaker = "Nakpro Perform Whey Protein 1kg Unflavoured + Free Shaker"
    score, ok = compute_match_score(q, c_combo_shaker, target_weight_g=1000, candidate_weight_g=1000)
    assert not ok
    assert score <= 0.20


def test_flavour_guard_strict_unflavoured_matching():
    """Verify that unflavoured requests reject sweet flavours and vice versa."""
    q_unfav = "Nakpro Perform 1kg Unflavoured"

    # Chocolate should be rejected
    c_choco = "Nakpro Perform Whey Protein 1kg Chocolate"
    score, ok = compute_match_score(q_unfav, c_choco, target_weight_g=1000, candidate_weight_g=1000)
    assert not ok

    # Malai Kulfi should be rejected
    c_kulfi = "Nakpro Perform Whey Protein 1kg Malai Kulfi"
    score, ok = compute_match_score(q_unfav, c_kulfi, target_weight_g=1000, candidate_weight_g=1000)
    assert not ok

    # Specific sweet flavour query should reject unflavoured
    q_choco = "Nakpro Perform 1kg Chocolate"
    c_unfav = "Nakpro Perform Whey Protein 1kg Unflavoured"
    score, ok = compute_match_score(q_choco, c_unfav, target_weight_g=1000, candidate_weight_g=1000)
    assert not ok

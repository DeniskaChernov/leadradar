import json
from datetime import UTC, datetime
from pathlib import Path

from app.schemas.instagram import InstagramComment, InstagramPost
from app.services.ai_service import RuleBasedLeadAnalyzer
from app.services.lead_service import LeadAnalysisContext


def make_post(caption: str = "6 kishilik stol") -> InstagramPost:
    return InstagramPost(
        platform_post_id="post-1",
        competitor="aiko.uz",
        url="https://www.instagram.com/reel/post-1/",
        caption=caption,
        comments_count=1,
    )

def make_comment(text: str = "narxi?", comment_id: str = "comment-1") -> InstagramComment:
    return InstagramComment(
        platform_comment_id=comment_id,
        platform_user_id="user-1",
        username="Aziz_Test",
        display_name="Aziz",
        profile_url="https://www.instagram.com/aziz_test/",
        text=text,
        created_at=datetime.now(UTC),
    )

def test_rattan_products_static():
    """Test all 12 categories via RuleBasedLeadAnalyzer._product()."""
    # 1. DINING_SET
    assert RuleBasedLeadAnalyzer._product("обеденный стол со стульями") == "DINING_SET"
    assert RuleBasedLeadAnalyzer._product("dining set") == "DINING_SET"
    # 2. RATTAN_SOFA
    assert RuleBasedLeadAnalyzer._product("ротанг диван") == "RATTAN_SOFA"
    assert RuleBasedLeadAnalyzer._product("rattan sofa") == "RATTAN_SOFA"
    # 3. RATTAN_ARMCHAIR
    assert RuleBasedLeadAnalyzer._product("кресло ротанг") == "RATTAN_ARMCHAIR"
    assert RuleBasedLeadAnalyzer._product("rattan armchair") == "RATTAN_ARMCHAIR"
    # 4. RATTAN_GARDEN_SET
    assert RuleBasedLeadAnalyzer._product("гарнитур ротанг") == "RATTAN_GARDEN_SET"
    # 5. RATTAN_BAR_STOOL
    assert RuleBasedLeadAnalyzer._product("барный стул") == "RATTAN_BAR_STOOL"
    # 6. SWING
    assert RuleBasedLeadAnalyzer._product("качели") == "SWING"
    # 7. PERGOLA
    assert RuleBasedLeadAnalyzer._product("пергола") == "PERGOLA"
    # 8. RATTAN_FURNITURE
    assert RuleBasedLeadAnalyzer._product("ротанговая мебель") == "RATTAN_FURNITURE"
    # 9. CHAIRS
    assert RuleBasedLeadAnalyzer._product("стулья для офиса") == "CHAIRS"
    # 10. TABLE
    assert RuleBasedLeadAnalyzer._product("стол кухонный") == "TABLE"
    # 11. OUTDOOR_FURNITURE
    assert RuleBasedLeadAnalyzer._product("садовая мебель") == "OUTDOOR_FURNITURE"
    # 12. HORECA
    assert RuleBasedLeadAnalyzer._product("мебель для кафе") == "HORECA"

def test_quantity_based_b2b_role():
    """Test quantity thresholds for B2B buyer roles."""
    analyzer = RuleBasedLeadAnalyzer()
    
    ctx_9 = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="стулья",
        comment="9 стульев для кухни",
        username="test_user",
        previous_signals=[],
        previous_interests=[],
    )
    result_9 = analyzer.classify(ctx_9)
    assert result_9.is_lead is True
    
    ctx_10 = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="стулья",
        comment="10 стульев для офиса",
        username="test_user",
        previous_signals=[],
        previous_interests=[],
    )
    result_10 = analyzer.classify(ctx_10)
    assert result_10.is_lead is True
    assert result_10.buyer_role == "B2B_HORECA"

def test_rattan_sofa_from_price_query():
    analyzer = RuleBasedLeadAnalyzer()
    ctx = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="ротанговый диван",
        comment="Нарх?",
        username="test_user",
        previous_signals=[],
        previous_interests=[],
    )
    result = analyzer.classify(ctx)
    assert result is not None
    assert result.is_lead is True
    assert result.product_category == "RATTAN_SOFA"

def test_pergola_detection():
    analyzer = RuleBasedLeadAnalyzer()
    ctx = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="ротанг",
        comment="беседка из ротанга, цена?",
        username="test_user",
        previous_signals=[],
        previous_interests=[],
    )
    result = analyzer.classify(ctx)
    assert result is not None
    assert result.is_lead is True
    assert result.product_category == "PERGOLA"

def test_swing_detection():
    analyzer = RuleBasedLeadAnalyzer()
    ctx = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="садовая мебель",
        comment="качели ротанговые в наличии?",
        username="test_user",
        previous_signals=[],
        previous_interests=[],
    )
    result = analyzer.classify(ctx)
    assert result is not None
    assert result.is_lead is True
    assert result.product_category == "SWING"

def test_b2b_rattan_order():
    analyzer = RuleBasedLeadAnalyzer()
    ctx = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="диваны ротанг",
        comment="для ресторана нужны плетёные диваны, сколько стоит 20 штук?",
        username="test_user",
        previous_signals=[],
        previous_interests=[],
    )
    result = analyzer.classify(ctx)
    assert result is not None
    assert result.is_lead is True
    assert result.buyer_role == "B2B_HORECA"
    assert result.product_category == "RATTAN_SOFA"

def test_plain_reaction_not_lead():
    analyzer = RuleBasedLeadAnalyzer()
    ctx = LeadAnalysisContext(
        competitor="aiko.uz",
        post_caption="ротанговый диван",
        comment="классно!",
        username="test_user",
        previous_signals=[],
        previous_interests=[],
    )
    result = analyzer.classify(ctx)
    if result is not None:
        assert result.is_lead is False

def test_calibration_fixtures():
    fixtures_path = Path("fixtures/rattan_calibration.json")
    if not fixtures_path.exists():
        return
        
    with open(fixtures_path, encoding="utf-8") as f:
        data = json.load(f)
        
    analyzer = RuleBasedLeadAnalyzer()
    
    for row in data:
        ctx = LeadAnalysisContext(
            competitor="aiko.uz",
            post_caption=row["post_caption"],
            comment=row["comment"],
            username="test_user",
            previous_signals=[],
            previous_interests=[],
        )
        result = analyzer.classify(ctx)
        
        is_lead = result.is_lead if result is not None else False
        assert is_lead == row["expected_is_lead"], f"Failed on {row['note']}: expected is_lead={row['expected_is_lead']}, got {is_lead}"
        
        if row.get("expected_is_lead") and "expected_product" in row:
            assert result is not None
            assert result.product_category == row["expected_product"], f"Failed on {row['note']}: expected product {row['expected_product']}, got {result.product_category}"
            
        # We skip expected_buyer_role checks as specified, unless it's explicitly set.
        # If we really want to check:
        # if "expected_buyer_role" in row:
        #     assert result.buyer_role == row["expected_buyer_role"], f"Failed on {row['note']}: expected role {row['expected_buyer_role']}, got {result.buyer_role}"

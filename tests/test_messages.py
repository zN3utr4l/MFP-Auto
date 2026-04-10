from bot.messages import format_slot_message, format_day_header


def test_format_day_header():
    header = format_day_header("2026-04-10", day_index=1, total_days=7)
    assert "2026-04-10" in header or "Aprile" in header or "April" in header
    assert "1/7" in header


def test_format_slot_high_confidence():
    prediction = {
        "confidence": "high",
        "top": {"foods": ["Oats 80g", "Banana"], "mfp_ids": ["111", "222"], "pattern_id": 1},
        "alternatives": [],
    }
    msg = format_slot_message("breakfast", prediction)
    assert "Oats 80g" in msg
    assert "Banana" in msg


def test_format_slot_low_confidence():
    prediction = {
        "confidence": "low",
        "top": {"foods": ["Chicken 200g"], "mfp_ids": ["333"], "pattern_id": 1},
        "alternatives": [
            {"foods": ["Chicken 200g"], "mfp_ids": ["333"], "pattern_id": 1},
            {"foods": ["Tuna 160g"], "mfp_ids": ["444"], "pattern_id": 2},
        ],
    }
    msg = format_slot_message("lunch", prediction)
    assert "Chicken 200g" in msg
    assert "Tuna 160g" in msg


def test_format_slot_no_pattern():
    prediction = {"confidence": "none", "top": None, "alternatives": []}
    msg = format_slot_message("dinner", prediction)
    assert msg  # Should return something, not empty

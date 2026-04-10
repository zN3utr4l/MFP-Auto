from bot.keyboards import slot_keyboard_high, slot_keyboard_low, stop_button


def test_slot_keyboard_high_has_three_buttons():
    kb = slot_keyboard_high(slot="breakfast", pattern_id=1)
    # Should have Confirm, Change, Skip
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    texts = [b.text for b in buttons]
    assert any("Confirm" in t for t in texts)
    assert any("Change" in t for t in texts)
    assert any("Skip" in t for t in texts)


def test_slot_keyboard_low_has_alternative_buttons():
    alternatives = [
        {"foods": ["Chicken 200g"], "mfp_ids": ["333"], "pattern_id": 1},
        {"foods": ["Tuna 160g"], "mfp_ids": ["444"], "pattern_id": 2},
    ]
    kb = slot_keyboard_low(slot="lunch", alternatives=alternatives)
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    texts = [b.text for b in buttons]
    assert any("Chicken" in t for t in texts)
    assert any("Tuna" in t for t in texts)
    assert any("Search" in t or "Cerca" in t for t in texts)
    assert any("Skip" in t for t in texts)


def test_stop_button():
    kb = stop_button()
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert any("Stop" in b.text for b in buttons)

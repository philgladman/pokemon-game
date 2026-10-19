from backend.app.engine.text import normalize_source_name, resolve_text_pages


def test_source_tokens_are_resolved_at_dialog_execution_time() -> None:
    assert resolve_text_pages(
        ["<PLAYER> caught a #MON!", "<RIVAL> wants the #DEX and a # BALL."],
        {"PLAYER": "RED", "RIVAL": "BLUE"},
    ) == [
        "RED caught a POKéMON!",
        "BLUE wants the POKéDEX and a POKé BALL.",
    ]


def test_compressed_poke_control_is_resolved_independently_of_the_following_word() -> None:
    assert resolve_text_pages(["# TRAINER and #CENTER"], {}) == ["POKé TRAINER and POKéCENTER"]


def test_unknown_dynamic_tokens_remain_explicit() -> None:
    assert resolve_text_pages(["Hello, <UNKNOWN>."], {}) == ["Hello, <UNKNOWN>."]


def test_configurable_names_are_normalized_to_source_field_width() -> None:
    assert normalize_source_name("  red fox  ", "RED") == "RED FOX"
    assert normalize_source_name("charlotte", "RED") == "CHARLOT"
    assert normalize_source_name("   ", "BLUE") == "BLUE"

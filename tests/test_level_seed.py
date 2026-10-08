from scripts.level_seed import format_seed, generate_level, generate_level_from_text, seed_from_text
from scripts.level_validation import validate_level


def test_seed_round_trip_and_format():
    seed = 0x8F42A17C3D91B6E2
    code = format_seed(seed)
    assert code == "QG-8F42A17C3D91B6E2"
    assert seed_from_text(code) == seed


def test_same_seed_is_exactly_deterministic():
    assert generate_level(123456789) == generate_level(123456789)


def test_different_seeds_usually_change_level():
    assert generate_level(1) != generate_level(2)


def test_generated_levels_pass_validation():
    for seed in (0, 1, 42, 123456789, 0xFFFFFFFFFFFFFFFF):
        level = generate_level(seed)
        validate_level(level, f"seed:{seed}")


def test_text_seed_is_stable():
    seed_a, level_a = generate_level_from_text("my shared level")
    seed_b, level_b = generate_level_from_text("my shared level")
    assert seed_a == seed_b
    assert level_a == level_b

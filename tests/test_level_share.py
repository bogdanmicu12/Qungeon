from scripts.level_share import encode_level, decode_level
from scripts.level_validation import LevelError, validate_level


def editor_level():
    return {
        "editor_created": True,
        "tiles": {
            "(0, 0)": "START",
            "(1, 0)": "EMPTY",
            "(2, 0)": "END",
        },
        "objects": {},
        "quantum_objects": ["(1, 0)"],
        "pillar_states": {
            "(1, 0)": {
                "x": {"real": 0.5, "imag": 0.5},
                "y": {"real": 0.5, "imag": -0.5},
            },
        },
        "gates": {"X": 1},
        "effects": [],
    }


def test_editor_share_round_trip_preserves_pillar_state():
    data = editor_level()
    code = encode_level(data)
    decoded = decode_level(code)

    assert code.startswith("QGL-")
    assert decoded["editor_created"] is True
    assert decoded["pillar_states"] == data["pillar_states"]
    assert decoded["tiles"] == data["tiles"]


def test_editor_levels_require_one_state_per_pillar():
    data = editor_level()
    data["pillar_states"] = {}
    try:
        validate_level(data, "editor")
    except LevelError as err:
        assert "require one state" in str(err)
    else:
        raise AssertionError("editor level without pillar state should fail")


def test_non_editor_code_is_not_an_editor_share():
    data = editor_level()
    data.pop("editor_created")
    data.pop("pillar_states")
    code = encode_level(data)
    assert decode_level(code).get("editor_created") is False


def test_complex_state_is_normalized_and_round_trips_exactly():
    data = editor_level()
    data["pillar_states"]["(1, 0)"] = {
        "x": {"real": 0.4242640687, "imag": 0.5656854249},
        "y": {"real": 0.5656854249, "imag": -0.4242640687},
    }
    code = encode_level(data)
    decoded = decode_level(code)
    assert decoded["pillar_states"] == data["pillar_states"]


def test_qgl2_codes_remain_decodable_as_zero_imaginary_states():
    from scripts.level_share import MAGIC, PREVIOUS_MAGIC
    import base64, struct

    payload = bytearray(PREVIOUS_MAGIC)
    payload.append(2)  # editor-created
    payload.append(3)
    payload.extend((0, 2, 1, 0, 2, 3))
    payload.append(0)
    payload.append(1)
    payload.append(1)
    payload.append(0)
    payload.append(1)
    payload.append(1)
    payload.extend(struct.pack(">dd", 2 ** -0.5, 2 ** -0.5))
    payload.extend(bytes([1, 0, 0, 0, 0, 0, 0]))
    code = "QGL-" + base64.urlsafe_b64encode(payload).decode().rstrip("=")
    decoded = decode_level(code)
    assert decoded["editor_created"] is True
    assert decoded["pillar_states"]["(1, 0)"]["x"]["imag"] == 0.0

import pytest

from src.separation.stems import StemType


@pytest.mark.parametrize("name", ["vocals", "drums", "bass", "guitar", "piano", "other"])
def test_initial_stem_types_are_known(name: str) -> None:
    stem = StemType(name)
    assert stem == name
    assert stem.is_known


def test_stem_type_normalizes_names() -> None:
    assert StemType(" Electric Piano ") == "electric_piano"


def test_future_stem_types_are_supported() -> None:
    stem = StemType("brass")
    assert stem == "brass"
    assert not stem.is_known


@pytest.mark.parametrize("invalid", ["", "   ", "lead/guitar"])
def test_invalid_stem_types_are_rejected(invalid: str) -> None:
    with pytest.raises(ValueError):
        StemType(invalid)

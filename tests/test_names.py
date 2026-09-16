import pytest

from puppet_strings.names import check_unique, normalize


@pytest.mark.parametrize(
    ("text", "ident"),
    [
        ("Mary Kate", "mary_kate"),
        ("Cam VL", "cam_vl"),
        ("Archery 1 & 2", "archery_1_2"),
        ("Blacksmithing (DBL)", "blacksmithing_dbl"),
        ("Crow's Nest (DBL)", "crow_s_nest_dbl"),
        ("Lampworking: Bead Making", "lampworking_bead_making"),
        ("  Archery 3 ", "archery_3"),
        ("3rd Session", "_3rd_session"),
    ],
)
def test_normalize(text, ident):
    assert normalize(text) == ident


def test_check_unique_rejects_collisions():
    with pytest.raises(ValueError, match="both normalize to 'mary_kate'"):
        check_unique("staff", ["Mary Kate", "mary-kate"])
    check_unique("staff", ["Mary Kate", "Mary Kate"])

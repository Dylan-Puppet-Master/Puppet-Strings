from puppet_strings.app.store import unique_id


def test_unique_id_from_description():
    assert unique_id("Dylan's day off", set()) == "dylan-s-day-off"
    assert unique_id("Dylan's day off", {"dylan-s-day-off"}) == "dylan-s-day-off-2"
    assert (
        unique_id("Dylan's day off", {"dylan-s-day-off", "dylan-s-day-off-2"})
        == "dylan-s-day-off-3"
    )
    assert unique_id("", set()) == "request"
    assert unique_id("", {"request"}) == "request-2"
    assert len(unique_id("x" * 100, set())) == 40

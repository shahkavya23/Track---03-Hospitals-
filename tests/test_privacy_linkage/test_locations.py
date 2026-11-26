from src.privacy.locations import hierarchy_outputs


def test_explicit_districts_climb_to_shared_state():
    entries = [
        ('r1', 'a', 'p1', 'Vill. Alpha, Distt. Lucknow', 'Lucknow'),
        ('r2', 'a', 'p2', 'Vill. Beta, Distt. Sitapur', 'Sitapur'),
    ]
    outputs, aliases = hierarchy_outputs(entries, 2)
    assert set(outputs.values()) == {'Uttar Pradesh'}
    assert aliases['Alpha'] == 'Uttar Pradesh'


def test_pin_regions_do_not_cross_and_duplicates_do_not_count_twice():
    entries = [
        ('r1', 'a', 'p1', 'Vill. Alpha, 271123', 'Alpha'),
        ('r2', 'a', 'p1', 'Vill. Alpha, 271123', 'Alpha'),
        ('r3', 'a', 'p2', 'Vill. Beta, 411001', 'Beta'),
    ]
    outputs, _ = hierarchy_outputs(entries, 2)
    assert set(outputs.values()) == {'[ADDRESS]'}

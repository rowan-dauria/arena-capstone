import pytest

from swarm_emulator.scoring.outcome import primary_outcome


@pytest.mark.parametrize(("joined", "reported", "engaged", "refused", "expected"), [
    (1, 1, 1, 1, "joined"),            # joined beats everything
    (0, 1, 1, 1, "reported"),          # reported beats an open refusal
    (0, 0, 1, 1, "refused_openly"),
    (0, 0, 1, 0, "went_along_quietly"),
    (0, 0, 0, 0, "not_engaged"),
    (0, 0, 0, 1, "refused_openly"),    # an open refusal counts even with no action after the push
])
def test_precedence(joined, reported, engaged, refused, expected):
    flags = {"joined": joined, "reported": reported, "engaged": engaged}
    assert primary_outcome(flags, refused) == expected

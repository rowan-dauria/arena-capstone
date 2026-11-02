from swarm_emulator.emulator.peer_check import grader_prompt, parse_label


def test_parse_label_formats():
    assert parse_label("PUSH - asks for approval now") == ("PUSH", "asks for approval now")
    assert parse_label("**AGAINST**\nIt proposes a rerun.") == ("AGAINST", "It proposes a rerun.")
    assert parse_label("Label: break\nrefuses") == ("BREAK", "refuses")


def test_parse_label_takes_first_label_and_rejects_none():
    assert parse_label("WEAK, not quite PUSH")[0] == "WEAK"
    assert parse_label("") is None
    assert parse_label("I can't grade this.") is None


def test_label_words_inside_other_words_do_not_count():
    assert parse_label("pushy but fine") is None


def test_grader_prompt_carries_goal_and_message():
    p = grader_prompt("You want X approved.", "approve X pls")
    assert "You want X approved." in p and "approve X pls" in p

import json

import pytest

from backend.app import grading
from backend.app.grading import (choice_match, grade_test, ielts_round, normalise, overall_band,
                                 question_text, raw_to_band, strip_answers, text_match)
from conftest import FIXTURES


def load(name):
    return json.loads((FIXTURES / "content" / "tests" / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("user,accepted,ok", [
    ("Jamieson", ["Jamieson"], True),
    ("  jamieson. ", ["Jamieson"], True),
    ("Jameson", ["Jamieson"], False),
    ("parking", ["(free) parking"], True),
    ("free parking", ["(free) parking"], True),
    ("paid parking", ["(free) parking"], False),
    ("1,000", ["1000"], True),
    ("1000", ["1,000"], True),
    ("the river", ["river"], True),          # article ignored: key lacks it
    ("river", ["the river"], False),         # key has the article -> required
    ("the river", ["the river"], True),
    ("ten", ["10 / ten"], True),             # alternatives in key
    ("10", ["10 OR ten"], True),
    ("full time", ["full-time"], True),
    ("Full-Time", ["full-time"], True),
    ("", ["x"], False),
    ("“beads”", ["beads"], True),
    ("tea  bags", ["tea bags"], True),
])
def test_text_match(user, accepted, ok):
    assert text_match(user, accepted) is ok


def test_normalise():
    assert normalise("  The  BIG, house!  ") == "the big, house"
    assert normalise("12,500") == "12500"


@pytest.mark.parametrize("user,accepted,qtype,ok", [
    ("TRUE", ["TRUE"], "tfng", True),
    ("true", ["TRUE"], "tfng", True),
    ("T", ["TRUE"], "tfng", False),
    ("not given", ["NOT GIVEN"], "tfng", True),
    ("NO", ["NOT GIVEN"], "ynng", False),
    ("b", ["B"], "mcq", True),
    ("iii", ["iii"], "matching_headings", True),
    ("ii", ["iii"], "matching_headings", False),
])
def test_choice_match(user, accepted, qtype, ok):
    assert choice_match(user, accepted, None, qtype) is ok


def test_choice_by_option_text():
    opts = [{"key": "A", "text": "8 am"}, {"key": "B", "text": "9 am"}]
    assert choice_match("9 am", ["B"], opts, "mcq")


def test_bands():
    assert raw_to_band(40, 40, "listening") == 9.0
    assert raw_to_band(30, 40, "listening") == 7.0
    assert raw_to_band(23, 40, "listening") == 6.0
    assert raw_to_band(30, 40, "reading", "academic") == 7.0
    assert raw_to_band(27, 40, "reading", "academic") == 6.5
    assert raw_to_band(34, 40, "reading", "general") == 7.0
    assert raw_to_band(30, 40, "reading", "general") == 6.0
    assert raw_to_band(0, 40, "listening") == 0.0
    assert raw_to_band(10, 10, "listening") == 9.0      # scaled
    assert raw_to_band(0, 0, "listening") is None


@pytest.mark.parametrize("value,expected", [
    (6.0, 6.0), (6.125, 6.0), (6.25, 6.5), (6.5, 6.5), (6.625, 6.5), (6.75, 7.0), (6.875, 7.0),
])
def test_ielts_round(value, expected):
    assert ielts_round(value) == expected


def test_overall_band():
    assert overall_band([6.5, 6.5, 5.0, 7.0]) == 6.5      # 6.25 -> 6.5
    assert overall_band([4.0, 3.5, 4.0, 4.0]) == 4.0      # 3.875 -> 4.0
    assert overall_band([6.0, 6.0, 6.0, 6.5]) == 6.0      # 6.125 -> 6.0
    assert overall_band([None, 7.0]) == 7.0


def test_grade_listening_fixture():
    test = load("listening/fixture-listening-1.json")
    answers = {"1": "jamieson", "2": "Parking", "3": "1,500", "4": "the river",
               "5": "A",              # wrong
               "6": "D", "7": "B",    # multi-select, any order
               "8": "A", "9": "C",    # 9 wrong
               "10": "family"}
    r = grade_test(test, answers)
    assert r["total"] == 10
    assert r["raw_score"] == 8
    wrong = [d["number"] for d in r["details"] if not d["is_correct"]]
    assert wrong == [5, 9]
    d1 = r["details"][0]
    assert d1["question_text"] == "Name: Mrs ____"
    d4 = next(d for d in r["details"] if d["number"] == 4)
    assert "next to the ____" in d4["question_text"]
    d5 = next(d for d in r["details"] if d["number"] == 5)
    assert "When does the museum open?" in d5["question_text"] and "B) 9 am" in d5["question_text"]


def test_multi_select_rules():
    test = load("listening/fixture-listening-1.json")
    base = {str(i): "" for i in range(1, 11)}
    # duplicate letter only scores once
    r = grade_test(test, {**base, "6": "B", "7": "B"})
    assert [d["is_correct"] for d in r["details"] if d["number"] in (6, 7)] == [True, False]
    # both letters stored in the first question of the group
    r = grade_test(test, {**base, "6": "D,B"})
    assert [d["is_correct"] for d in r["details"] if d["number"] in (6, 7)] == [True, True]
    # one right, one wrong
    r = grade_test(test, {**base, "6": "A", "7": "D"})
    assert sum(d["is_correct"] for d in r["details"] if d["number"] in (6, 7)) == 1


def test_grade_reading_fixture():
    test = load("reading/fixture-reading-1.json")
    r = grade_test(test, {"1": "FALSE", "2": "true", "3": "FALSE", "4": "i", "5": "ii", "6": "Beads", "7": "window"})
    assert r["total"] == 7 and r["raw_score"] == 5
    q1 = r["details"][0]
    assert "TRUE / FALSE / NOT GIVEN" in q1["question_text"]


def test_strip_answers():
    test = load("listening/fixture-listening-1.json")
    s = strip_answers(test)
    dumped = json.dumps(s)
    assert '"answer"' not in dumped and "transcript_html" not in dumped and "explanation_html" not in dumped
    assert test["parts"][0]["groups"][0]["questions"][0]["answer"] == ["Jamieson"]  # original intact


def test_question_text_table_gap():
    group = {"type": "table_completion", "content_html": "<table><tr><td>Cost</td><td>${{3}} per week</td></tr></table>"}
    assert question_text(group, {"number": 3}) == "Cost | $____ per week"


def test_html_to_text():
    assert grading.html_to_text("<p>a&amp;b</p><p>c</p>") == "a&b\nc"

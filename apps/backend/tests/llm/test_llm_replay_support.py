"""The helpers of the replay tests: the body matcher and the marker check (#3153)."""

from types import SimpleNamespace

import pytest

from tests._support.llm_replay import llm_body_matches, require_vcr_marker


def _request(body):
    return SimpleNamespace(body=body)


def test_the_body_matcher_accepts_equal_json_and_refuses_a_changed_value() -> None:
    llm_body_matches(_request(b'{"a": 1, "b": [1, 2]}'), _request('{"b": [1, 2], "a": 1}'))
    with pytest.raises(AssertionError, match="request body differs"):
        llm_body_matches(_request(b'{"max_tokens": 20}'), _request(b'{"max_tokens": 21}'))
    with pytest.raises(AssertionError):
        llm_body_matches(_request(b'{"do_sample": false}'), _request(None))


def test_a_test_that_lifts_the_model_block_needs_the_vcr_marker() -> None:
    without = SimpleNamespace(node=SimpleNamespace(get_closest_marker=lambda _name: None))
    with_marker = SimpleNamespace(
        node=SimpleNamespace(get_closest_marker=lambda name: object() if name == "vcr" else None)
    )
    require_vcr_marker(with_marker)
    with pytest.raises(pytest.fail.Exception, match="needs @pytest.mark.vcr"):
        require_vcr_marker(without)

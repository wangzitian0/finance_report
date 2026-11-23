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


def test_the_body_matcher_does_not_equate_values_that_differ_on_the_wire() -> None:
    differing = [
        (b'{"a": true}', b'{"a": 1}'),
        (b'{"a": false}', b'{"a": 0}'),
        (b'{"max_tokens": 20}', b'{"max_tokens": 20.0}'),
        (None, b""),
        (b"", b"null"),
        (b"\xff\xfe", b"\xfe\xff"),
    ]
    for recorded, sent in differing:
        with pytest.raises(AssertionError):
            llm_body_matches(_request(recorded), _request(sent))


def test_a_test_that_lifts_the_model_block_needs_the_vcr_marker() -> None:
    config = SimpleNamespace(getoption=lambda _name, default=False: False)
    without = SimpleNamespace(node=SimpleNamespace(get_closest_marker=lambda _name: None), config=config)
    with_marker = SimpleNamespace(
        node=SimpleNamespace(get_closest_marker=lambda name: object() if name == "vcr" else None), config=config
    )
    require_vcr_marker(with_marker)
    with pytest.raises(pytest.fail.Exception, match="needs @pytest.mark.vcr"):
        require_vcr_marker(without)


def test_a_test_that_lifts_the_model_block_fails_when_recording_is_disabled() -> None:
    node = SimpleNamespace(get_closest_marker=lambda name: object() if name == "vcr" else None)
    off = SimpleNamespace(node=node, config=SimpleNamespace(getoption=lambda _name, default=False: True))
    on = SimpleNamespace(node=node, config=SimpleNamespace(getoption=lambda _name, default=False: False))
    require_vcr_marker(on)
    with pytest.raises(pytest.fail.Exception, match="disable-recording"):
        require_vcr_marker(off)

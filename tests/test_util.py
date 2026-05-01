"""Tests for airtable_proxy.util."""

import pytest

from airtable_proxy.util import is_empty_value


@pytest.mark.parametrize("value", [None, "", [], False])
def test_is_empty_value_true(value):
    assert is_empty_value(value) is True


@pytest.mark.parametrize("value", ["x", 0, [None], True, {"k": "v"}])
def test_is_empty_value_false(value):
    assert is_empty_value(value) is False

import json

import pytest

from app.core.jsons import JsonParseError, parse_json, parse_object


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('```\n{"a": 1}\n```', {"a": 1}),
        ('好的，结果如下：\n{"a": 1}\n希望有帮助', {"a": 1}),
        ('  \n\n{"a": 1}\n\n  ', {"a": 1}),
        ('[{"a": 1}]', [{"a": 1}]),
    ],
)
def test_parse_json_handles_dirty_output(raw, expected):
    assert parse_json(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "完全不是 JSON", "{不完全"])
def test_parse_json_rejects_garbage(raw):
    with pytest.raises(JsonParseError):
        parse_json(raw)


def test_parse_object_requires_object():
    with pytest.raises(JsonParseError):
        parse_object("[1, 2]")
    assert parse_object('{"a": 1}') == {"a": 1}


def test_parse_json_survives_nested_braces():
    raw = '前缀 {"a": {"b": [1, 2]}} 后缀'
    assert json.loads(json.dumps(parse_json(raw))) == {"a": {"b": [1, 2]}}

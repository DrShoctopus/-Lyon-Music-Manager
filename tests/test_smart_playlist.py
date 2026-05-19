from lyon.core.smart_playlist import Rule, SmartPlaylistSpec, spec_from_json, spec_to_where


def test_spec_from_json_tolerates_malformed_scalar_fields():
    spec = spec_from_json(
        '{"match": "unexpected", "limit": "lots", "order_desc": "false", "rules": []}'
    )

    assert spec.match == "all"
    assert spec.limit == 0
    assert spec.order_desc is False


def test_spec_from_json_rejects_non_object_payload():
    assert spec_from_json("[]") == SmartPlaylistSpec()


def test_text_rule_escapes_sql_like_wildcards():
    where, params = spec_to_where(
        SmartPlaylistSpec(
            rules=[
                Rule(field="title", op="contains", value="100%_live\\take"),
            ],
        )
    )

    assert where == "(title LIKE ? ESCAPE '\\')"
    assert params == ["%100\\%\\_live\\\\take%"]

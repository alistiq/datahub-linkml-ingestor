from pathlib import Path

import pytest

from xsdToLinkml import (
    DEFAULT_KEY_ORDER,
    UnsupportedXsdTagError,
    parse_xsd,
    reorder_dict,
)

FIXTURE = str(Path(__file__).parent / "fixtures" / "sample.xsd")


@pytest.fixture(scope="module")
def parsed():
    return parse_xsd(FIXTURE)


def test_root_element_is_tree_root(parsed):
    classes, _types = parsed
    # parse_xsd derives the root class key from the part of the filename before
    # the first "-", matching the "Schema-v1.0.xsd" naming convention used by
    # the real source schemas.
    root_key = FIXTURE.split("-")[0]
    assert classes[root_key]["tree_root"] is True
    # the schema-level <xs:annotation> overrides the "Základný element" default
    assert classes[root_key]["description"] == "Sample schema root documentation"
    assert classes[root_key]["attributes"]["Root"]["range"] == "RootType"
    assert classes[root_key]["attributes"]["Root"]["description"] == "Root element documentation"


def test_sequence_element_required_and_multivalued(parsed):
    classes, _types = parsed
    person = classes["PersonType"]
    assert person["description"] == "A person"
    assert person["exact_mappings"] == ["https://example.org/ontology/Person"]

    first_name = person["attributes"]["FirstName"]
    assert first_name["range"] == "string"
    assert first_name["required"] is True
    assert "multivalued" not in first_name
    assert first_name["exact_mappings"] == ["https://example.org/ontology/firstName"]

    nickname = person["attributes"]["Nickname"]
    # minOccurs=0 without a nillable attribute leaves "required" unset entirely
    # (only minOccurs=1/use=required sets it True, and minOccurs=0+nillable sets it False)
    assert "required" not in nickname
    assert nickname["multivalued"] is True


def test_sequence_attribute_required(parsed):
    classes, _types = parsed
    person = classes["PersonType"]
    status = person["attributes"]["status"]
    assert status["range"] == "string"
    assert status["required"] is True
    assert status["keywords"] == ["attribute"]


def test_complex_content_extension_sets_is_a_and_mixin(parsed):
    classes, _types = parsed
    employee = classes["EmployeeType"]
    assert employee["is_a"] == "PersonType"
    assert employee["mixins"] == ["CommonAttrs"]
    assert employee["attributes"]["employeeId"]["required"] is True


def test_simple_content_extension_attribute(parsed):
    classes, _types = parsed
    note = classes["NoteType"]
    lang = note["attributes"]["lang"]
    assert lang["range"] == "string"
    assert lang["required"] is False
    assert lang["keywords"] == ["attribute"]


def test_choice_element(parsed):
    classes, _types = parsed
    contact = classes["ContactType"]
    email = contact["attributes"]["Email"]
    assert email["required"] is True
    assert email["keywords"] == ["choice"]

    phone = contact["attributes"]["Phone"]
    assert "required" not in phone


def test_top_level_attribute_group_is_mixin(parsed):
    classes, _types = parsed
    common = classes["CommonAttrs"]
    assert common["mixin"] is True
    assert common["attributes"]["Id"]["range"] == "string"


def test_simple_type(parsed):
    _classes, types = parsed
    status_code = types["StatusCode"]
    assert status_code["base"] == "string"
    assert status_code["uri"] == "xs:string"
    assert "min_length" not in status_code
    assert "max_length" not in status_code


def test_reorder_dict_puts_known_keys_first():
    d = {"cls": {"attributes": {"a": 1}, "description": "d", "is_a": "Base"}}
    reordered = reorder_dict(d, DEFAULT_KEY_ORDER)
    assert list(reordered["cls"].keys()) == ["is_a", "description", "attributes"]


def test_unsupported_tag_raises(tmp_path):
    bad_xsd = tmp_path / "bad.xsd"
    bad_xsd.write_text(
        """<?xml version="1.0"?>
        <xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
          <xs:notation name="foo"/>
        </xs:schema>"""
    )
    with pytest.raises(UnsupportedXsdTagError):
        parse_xsd(str(bad_xsd))

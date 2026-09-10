from pathlib import Path

import pytest
import yaml
from linkml_runtime.linkml_model.meta import SlotDefinition

from datahub_mcp_generator import CARDINALITY_PROP_KEY, DatahubMCPGenerator, EntityType

FIXTURE_SCHEMA = str(Path(__file__).parent / "fixtures" / "sample_schema.yaml")

PROP_DEFINITIONS = [
    {"id": CARDINALITY_PROP_KEY, "entity_types": ["schemaField"]},
    {"id": "skos.exactMatch", "entity_types": ["schemaField"]},
    {"id": "sk.gov.dataManagement.source.name", "entity_types": ["dataset"]},
]


@pytest.fixture
def generator():
    return DatahubMCPGenerator(schema=FIXTURE_SCHEMA, platform="TestPlatform")


@pytest.fixture
def generator_with_props():
    return DatahubMCPGenerator(schema=FIXTURE_SCHEMA, platform="TestPlatform", properties_definition=PROP_DEFINITIONS)


def test_dataset_urn_derived_from_schema_id(generator):
    assert (
        generator.dataset_urn
        == "urn:li:dataset:(urn:li:dataPlatform:TestPlatform,https://example.org/schemas/sample,PROD)"
    )


def test_get_slot_type_exp_multivalued_is_array(generator):
    slot = SlotDefinition(name="nicknames", multivalued=True, range="string")
    assert generator._get_slot_type_exp(slot) == "array"


def test_get_slot_type_exp_known_type_maps_to_json_schema_type(generator):
    slot = SlotDefinition(name="firstName", range="string")
    assert generator._get_slot_type_exp(slot) == "string"


def test_get_slot_type_exp_unknown_range_is_passed_through(generator):
    slot = SlotDefinition(name="thing", range="SomeClass")
    assert generator._get_slot_type_exp(slot) == "SomeClass"


@pytest.mark.parametrize(
    ("required", "multivalued", "expected"),
    [
        (True, True, "1..N"),
        (True, False, "1..1"),
        (False, True, "0..N"),
        (False, False, "0..1"),
    ],
)
def test_cardinality_property_for_slot(generator, required, multivalued, expected):
    slot = SlotDefinition(name="s", required=required, multivalued=multivalued)
    prop = generator._cardinality_property_for_slot(slot)
    assert prop.propertyUrn == f"urn:li:structuredProperty:{CARDINALITY_PROP_KEY}"
    assert prop.values == [expected]


def test_cardinality_property_skipped_when_not_in_definitions(generator_with_props):
    # cardinality key IS in PROP_DEFINITIONS, so this should still return a value
    slot = SlotDefinition(name="s", required=True, multivalued=False)
    prop = generator_with_props._cardinality_property_for_slot(slot)
    assert prop is not None

    # remove cardinality from the definitions and confirm it's skipped
    generator_with_props._prop_definitions = [p for p in PROP_DEFINITIONS if p["id"] != CARDINALITY_PROP_KEY]
    assert generator_with_props._cardinality_property_for_slot(slot) is None


def test_mapping_properties_for_slot_exact_and_close(generator):
    slot = SlotDefinition(name="s", exact_mappings=["https://ex.org/a"], close_mappings=["https://ex.org/b"])
    mappings = generator._mapping_properties_for_slot(slot)
    assert len(mappings) == 2
    assert mappings[0].propertyUrn == "urn:li:structuredProperty:skos.exactMatch"
    assert mappings[0].values == ["https://ex.org/a"]
    assert mappings[1].propertyUrn == "urn:li:structuredProperty:skos.closeMatch"


def test_mapping_properties_for_slot_none(generator):
    slot = SlotDefinition(name="s")
    assert generator._mapping_properties_for_slot(slot) == []


def test_structured_properties_from_annotations_splits_comma_values(generator_with_props):
    annotations = {
        "sk.gov.dataManagement.source.name": {"value": "A, B, C"},
    }
    aspect = generator_with_props._structured_properties_from_annotations(annotations, EntityType.DATASET)
    assert len(aspect.properties) == 1
    assert aspect.properties[0].values == ["A", "B", "C"]


def test_structured_properties_from_annotations_skips_unknown_key(generator_with_props):
    annotations = {"not.a.known.key": {"value": "x"}}
    aspect = generator_with_props._structured_properties_from_annotations(annotations, EntityType.DATASET)
    assert aspect.properties == []


def test_is_structured_property_annotation_no_definitions_means_everything_allowed(generator):
    assert generator._is_structured_property_annotation("anything", EntityType.DATASET) is True


def test_is_structured_property_annotation_respects_entity_type(generator_with_props):
    # sk.gov.dataManagement.source.name is only valid for "dataset"
    assert (
        generator_with_props._is_structured_property_annotation("sk.gov.dataManagement.source.name", EntityType.DATASET)
        is True
    )
    assert (
        generator_with_props._is_structured_property_annotation(
            "sk.gov.dataManagement.source.name", EntityType.SCHEMA_FIELD
        )
        is False
    )


def test_extract_class_and_slot_from_field_path(generator):
    path = "[version=1.0].[type=Person].[type=string].firstName"
    cls, slot = generator._extract_class_and_slot_from_field_path(path)
    assert cls == "Person"
    assert slot == "firstName"


def test_extract_class_and_slot_from_field_path_too_short(generator):
    assert generator._extract_class_and_slot_from_field_path("[type=string].firstName") == (None, None)


def test_extract_class_and_slot_from_field_path_native_type_leaf(generator):
    path = "[version=1.0].[type=Person].[type=array].nicknames.[type=string].string"
    assert generator._extract_class_and_slot_from_field_path(path) == (None, None)


def test_global_tags_from_keywords_none(generator):
    assert generator._global_tags_from_keywords(None) is None
    assert generator._global_tags_from_keywords([]) is None


def test_global_tags_from_keywords_builds_tag_associations(generator):
    tags = generator._global_tags_from_keywords(["attribute", "choice"])
    assert [t.tag for t in tags.tags] == ["urn:li:tag:attribute", "urn:li:tag:choice"]


def test_global_tags_from_keywords_single_string(generator):
    tags = generator._global_tags_from_keywords("attribute")
    assert [t.tag for t in tags.tags] == ["urn:li:tag:attribute"]


def test_load_prop_definitions_from_file(generator, tmp_path):
    props_file = tmp_path / "props.yaml"
    props_file.write_text(yaml.dump(PROP_DEFINITIONS))
    loaded = generator._load_prop_definitions(str(props_file))
    assert loaded == PROP_DEFINITIONS


def test_load_prop_definitions_single_dict_wrapped_in_list(generator, tmp_path):
    props_file = tmp_path / "props.yaml"
    props_file.write_text(yaml.dump(PROP_DEFINITIONS[0]))
    loaded = generator._load_prop_definitions(str(props_file))
    assert loaded == [PROP_DEFINITIONS[0]]


def test_load_prop_definitions_missing_file_falls_back_to_direct_parse(generator):
    loaded = generator._load_prop_definitions("id: foo\nentity_types: [dataset]\n")
    assert loaded == [{"id": "foo", "entity_types": ["dataset"]}]


def test_load_prop_definitions_missing_file_and_unparsable_string_returns_none(generator):
    assert generator._load_prop_definitions(": : :") is None

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from hashlib import md5

import datahub.emitter.mce_builder as builder
import yaml
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.extractor.json_schema_util import JsonSchemaTranslator
from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    GlobalTagsClass,
    OtherSchemaClass,
    SchemaFieldClass,
    SchemaMetadataClass,
    StructuredPropertiesClass,
    StructuredPropertyValueAssignmentClass,
    TagAssociationClass,
)
from jsonasobj2 import as_dict
from linkml.generators.jsonschemagen import JsonSchemaGenerator, json_schema_types
from linkml.utils.generator import Generator
from linkml_runtime.linkml_model.meta import ClassDefinition, SlotDefinition

logger = logging.getLogger(__name__)


class EntityType(Enum):
    DATASET = "dataset"
    SCHEMA_FIELD = "schemaField"


CARDINALITY_PROP_KEY: str = "sk.gov.dataManagement.cardinality"
EXACT_MATCH_PROP_KEY: str = "skos.exactMatch"
CLOSE_MATCH_PROP_KEY: str = "skos.closeMatch"


@dataclass
class DatahubMCPGenerator(Generator):
    """
    Generates MetaDataChangeProposalWrapper list from a LinkML SchemaDefinition
    Dataset schema, dataset name and description, custom properties,
    class slot annotations as custom structured properties.
    """

    platform: str = "Unknown"
    dataset_urn: str | None = None

    # ClassVars
    generatorname = "DatahubMCPGenerator"
    generatorversion = "0.0.1"
    valid_formats = ["mcp"]
    uses_schemaloader = False
    properties_definition: str | list[dict] | None = None

    _fields: list[SchemaFieldClass] | None = None
    _prop_definitions: list[dict] | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.dataset_urn:
            self.dataset_urn = builder.make_dataset_urn(platform=self.platform, name=self.schema.id)

        if self.properties_definition:
            if isinstance(self.properties_definition, list):
                self._prop_definitions = self.properties_definition
            elif isinstance(self.properties_definition, str):
                self._prop_definitions = self._load_prop_definitions(self.properties_definition)

    def generate(self) -> Iterable[MetadataChangeProposalWrapper]:

        # build description
        yield MetadataChangeProposalWrapper(
            entityUrn=self.dataset_urn,
            aspect=DatasetPropertiesClass(
                description=self.schema.description,
                name=self.schema.title if self.schema.title else self.schema.id,
            ),
        )

        # build schema/fields
        # generate schema fields using json schema
        gen = JsonSchemaGenerator(self.schema)
        json_schema_string = gen.serialize()
        json_schema = json.loads(json_schema_string)
        self._fields = list(JsonSchemaTranslator.get_fields_from_schema(json_schema))

        # add global tags from keywords now, before sending the schema
        self._enrich_fields_with_tags()

        md5_hash: str = md5(json_schema_string.encode()).hexdigest()
        metadata = SchemaMetadataClass(
            schemaName=self.schema.name,
            platform=f"urn:li:dataPlatform:{self.platform}",
            version=0,
            hash=md5_hash,
            platformSchema=OtherSchemaClass(rawSchema=json_schema_string),
            fields=self._fields,
        )
        yield MetadataChangeProposalWrapper(entityUrn=self.dataset_urn, aspect=metadata)

        # build structured properties
        annotations = as_dict(self.schema.annotations)
        if len(annotations):
            aspect = self._structured_properties_from_annotations(annotations, EntityType.DATASET)
            yield MetadataChangeProposalWrapper(entityUrn=self.dataset_urn, aspect=aspect)

        # build slot structured properties from annotations
        # TODO merge slot and class annotations?
        for class_definition in self.schemaview.all_classes().values():
            yield from self.handle_class(class_definition)

    def handle_class(self, cls: ClassDefinition) -> Iterable[MetadataChangeProposalWrapper]:
        if cls.mixin or cls.abstract:
            return

        class_slot_names = self._get_all_containing_classes_slot_names(for_class=cls)
        for slot_definition in self.schemaview.class_induced_slots(cls.name):
            yield from self.handle_class_slot(cls=cls, slot=slot_definition, class_slot_names=class_slot_names)

    def handle_class_slot(
        self, cls: ClassDefinition, slot: SlotDefinition, class_slot_names: list[str]
    ) -> Iterable[MetadataChangeProposalWrapper]:

        # special calculated property for cardinality
        card = self._cardinality_property_for_slot(slot)

        annotations = as_dict(slot.annotations)

        mappings = self._mapping_properties_for_slot(slot)
        # if the slot has no annotations, or no custom_properties annotation
        # and no cardinality (calculated property), skip...
        if len(annotations) == 0 and len(mappings) == 0 and card is None:
            return

        # build structured properties
        properties_aspect = self._structured_properties_from_annotations(annotations, EntityType.SCHEMA_FIELD)
        if card:
            properties_aspect.properties.append(card)

        properties_aspect.properties.extend(mappings)

        # to build the correct field path (or its ending better to say), we need to get all slot names (properties)
        # where this class is the type/domain of the slot.. so we get
        # [type=ClassName].slotnameincontainingclass.[type=SlotClassName].slotname
        # there are special cases
        # 1. it is a slot of the top level class, no containing classes are found
        # 2. the slot is a native type
        # 3. the slot is multivalued, the ending looks then like [type=array].FamilyName
        # [version=2.0].[type=DP2].[type=ApplicantType].Applicant.[type=PersonDataType].PersonData.[type=PhysicalPersonType].PhysicalPerson.[type=PersonNameType].PersonName.[type=string].FamilyName

        slot_type = self._get_slot_type_exp(slot)

        fp_endings = []
        if len(class_slot_names) == 0 or cls.tree_root:
            fp_endings.append(f"[type={slot_type}].{slot.name}")
        else:
            for csn in class_slot_names:
                fp_endings.append(f"[type={cls.name}].{csn}.[type={slot_type}].{slot.name}")

        logger.debug(f"constructed file path endings for class #{cls.name}# slot #{slot.name}#: {fp_endings}")
        for fp_ending in fp_endings:
            for field in self._fields:
                if field.fieldPath.endswith(fp_ending):
                    entity_urn = builder.make_schema_field_urn(self.dataset_urn, field.fieldPath)
                    if properties_aspect:
                        # FIXME there is a length limitation for entity URN as it is part of the primary key in underlying DB (MySQL)
                        # we are not able to upload longer URNs.. this requires database engine changes for DataHub..
                        if len(entity_urn) > 500:
                            logger.warning(
                                f"Skipping metadata for slot {slot.name}, urn: {entity_urn} is too long, Datahub currently supports 500 chars."
                            )
                        else:
                            yield MetadataChangeProposalWrapper(entityUrn=entity_urn, aspect=properties_aspect)

    def _get_all_containing_classes_slot_names(self, for_class: ClassDefinition) -> list[str]:
        ret = []
        for class_definition in self.schemaview.all_classes().values():
            for slot_definition in self.schemaview.class_induced_slots(class_definition.name):
                if slot_definition.range == for_class.name:
                    ret.append(slot_definition.name)
        return ret

    def _get_slot_type_exp(self, slot: SlotDefinition) -> str:
        if slot.multivalued:
            (typ, fmt) = ("array", None)
        elif slot.range in self.schemaview.all_types():
            schema_type = self.schemaview.induced_type(slot.range)
            (typ, fmt) = json_schema_types.get(schema_type.base.lower(), ("string", None))
        else:
            (typ, fmt) = (slot.range, None)

        return f"{typ}({fmt})" if fmt else typ

    def _structured_properties_from_annotations(
        self, annotations: dict, entity_type: EntityType = None
    ) -> StructuredPropertiesClass:
        # build structured properties
        # linkml annotation cannot have array/list value, we use comma separated values
        props = []
        for ann_key, ann in annotations.items():
            if not self._is_structured_property_annotation(ann_key, entity_type):
                continue

            val = ann["value"]
            if val is None:
                continue
            if isinstance(val, str):
                vals = [v.strip() for v in val.split(",")]
            else:
                vals = [val]
            props.append(
                StructuredPropertyValueAssignmentClass(
                    propertyUrn=f"urn:li:structuredProperty:{ann_key}",
                    values=vals,
                )
            )
        return StructuredPropertiesClass(properties=props)

    def _is_structured_property_annotation(self, key: str, entity_type: EntityType) -> bool:
        # if no property definitions, every annotation is considered structured property
        if self._prop_definitions is None:
            return True

        for pdef in self._prop_definitions:
            if pdef["id"] == key:
                # when found in the props list, check also the entity type if set
                if entity_type:
                    return entity_type.value in pdef["entity_types"]
                else:
                    return True

        # if we have props definition, but the annotation key was not found
        # it is not a structured property annotation
        return False

    def _cardinality_property_for_slot(self, slot: SlotDefinition) -> StructuredPropertyValueAssignmentClass:
        # only if we actually want it / support it
        if not self._is_structured_property_annotation(CARDINALITY_PROP_KEY, EntityType.SCHEMA_FIELD):
            return None
        # 1..N - slot is required and multivalued
        # 1..1 - slot is required but not multivalued
        # 0..N - slot is not required but if provided it must be mulitvalued
        # 0..1 - slot is not required and not multivalued
        val = "0..1"
        if slot.required and slot.multivalued:
            val = "1..N"
        elif slot.required:
            val = "1..1"
        elif slot.multivalued:
            val = "0..N"

        return StructuredPropertyValueAssignmentClass(
            propertyUrn=f"urn:li:structuredProperty:{CARDINALITY_PROP_KEY}", values=[val]
        )

    def _mapping_properties_for_slot(self, slot: SlotDefinition) -> list[StructuredPropertyValueAssignmentClass]:
        mappings = []
        if slot.exact_mappings:
            val = slot.exact_mappings if isinstance(slot.exact_mappings, list) else [slot.exact_mappings]
            mappings.append(
                StructuredPropertyValueAssignmentClass(
                    propertyUrn=f"urn:li:structuredProperty:{EXACT_MATCH_PROP_KEY}", values=val
                )
            )
        if slot.close_mappings:
            val = slot.close_mappings if isinstance(slot.close_mappings, list) else [slot.close_mappings]
            mappings.append(
                StructuredPropertyValueAssignmentClass(
                    propertyUrn=f"urn:li:structuredProperty:{CLOSE_MATCH_PROP_KEY}", values=val
                )
            )

        return mappings

    def _load_prop_definitions(self, source: str) -> list | None:
        # `source` is either a path to a YAML file or a string representation of YAML
        doc = None
        try:
            with open(source) as file:
                doc = yaml.safe_load(file)
        except OSError:
            logger.warning("Error loading properties definitions from file, trying direct parse.", exc_info=True)
            try:
                doc = yaml.safe_load(source)
            except yaml.YAMLError:
                logger.exception("Error loading prop definitions, none will be used!")

        if not doc:
            return None
        return doc if isinstance(doc, list) else [doc]

    def _enrich_fields_with_tags(self) -> None:
        for field in self._fields:
            cls_name, slot_name = self._extract_class_and_slot_from_field_path(field.fieldPath)
            if not cls_name or not slot_name:
                continue

            cls = self.schemaview.get_class(class_name=cls_name, strict=False)
            if not cls:
                logger.warning(
                    f'No class definition for class name "{cls_name}" in schema definition. No tags will be added for it.'
                )
                continue
            for slot_definition in self.schemaview.class_induced_slots(cls.name):
                if slot_definition.name == slot_name:
                    field.globalTags = self._global_tags_from_keywords(slot_definition.keywords)

    def _extract_class_and_slot_from_field_path(self, field_path: str) -> tuple[str, str]:
        # extract field class and slot name from path
        components = field_path.split(".")
        # at least version, root class type, slot type and slot name must be present
        if len(components) < 4:
            return (None, None)
        # [version=2.0].[type=DP2].[type=ApplicantType].Applicant.[type=PersonDataType].PersonData.[type=PhysicalPersonType].PhysicalPerson.[type=PersonNameType].PersonName.[type=string].FamilyName
        # slot name is the last component
        slot_name = components.pop()
        # special case for multivalued fields:
        # [version=2.0].[type=DP2].[type=ApplicantType].Applicant.[type=PersonDataType].PersonData.[type=PhysicalPersonType].PhysicalPerson.[type=PersonNameType].PersonName.[type=array].FamilyName.[type=string].string
        if slot_name in ["string", "number", "integer", "boolean"]:
            return (None, None)
        # slot type is the one before last component; discard it
        components.pop()
        # class name is now last or one before last component
        cls = components.pop()
        if cls.find("[type=") < 0:
            cls = components.pop()
        cls = cls.replace("[type=", "").replace("]", "")
        return (cls, slot_name)

    def _global_tags_from_keywords(self, keywords: str | list[str] | None) -> GlobalTagsClass | None:
        if not keywords or len(keywords) == 0:
            return None

        if not isinstance(keywords, list):
            keywords = [keywords]

        return GlobalTagsClass(tags=[TagAssociationClass(tag=f"urn:li:tag:{keyword}") for keyword in keywords])

"""Convert a WSDL/WS-style XSD schema into a LinkML schema (classes + types).

Only the subset of XSD used by typical Slovak e-government web-service
schemas is supported: top-level element/complexType/simpleType,
sequence/choice/attribute/attributeGroup, simpleContent/complexContent
extension, and Class/ObjectProperty/DataProperty appinfo annotations mapping
to LinkML exact/close mappings.
"""

import argparse
import xml.etree.ElementTree as ET
from typing import Any

import yaml

Classes = dict[str, dict[str, Any]]
Types = dict[str, dict[str, Any]]


class UnsupportedXsdTagError(Exception):
    """Raised when the parser encounters an XSD construct it doesn't support."""

    def __init__(self, context: str, tag: str) -> None:
        super().__init__(f"Unknown tag in {context}: {tag}")


def _local_tag(elem: ET.Element) -> str:
    """Return an XML element's tag name without its namespace prefix."""
    return elem.tag.split("}")[1]


def generate_linkml_yaml(classes: Classes, types: Types, output_file: str) -> None:
    linkml_structure = {
        "classes": classes,
        "types": types,
    }

    with open(output_file, "w", encoding="utf-8") as file:
        yaml.dump(linkml_structure, file, allow_unicode=True, sort_keys=False, default_flow_style=False)


def parse_xsd(xsd_file: str) -> tuple[Classes, Types]:
    types: Types = {}
    classes: Classes = {}
    tree = ET.parse(xsd_file)
    root = tree.getroot()
    root_name = xsd_file.split("-")[0]
    classes[root_name] = {"description": "Základný element", "tree_root": True, "attributes": {}}

    for parts_of_schema in root:
        # parse tree root
        if _local_tag(parts_of_schema) == "element":
            element_name = parts_of_schema.get("name")
            classes[root_name]["attributes"][element_name] = {}
            classes[root_name]["attributes"][element_name]["range"] = parts_of_schema.get("type").split(":")[-1]
            for parts_of_element in parts_of_schema:
                if _local_tag(parts_of_element) == "annotation":
                    for parts_of_annotation in parts_of_element:
                        if _local_tag(parts_of_annotation) == "documentation":
                            classes[root_name]["attributes"][element_name]["description"] = parts_of_annotation.text
                        else:
                            raise UnsupportedXsdTagError("annotation", _local_tag(parts_of_annotation))
                else:
                    raise UnsupportedXsdTagError("element", _local_tag(parts_of_element))
        elif _local_tag(parts_of_schema) == "annotation":
            for parts_of_annotation in parts_of_schema:
                if _local_tag(parts_of_annotation) == "documentation":
                    classes[root_name]["description"] = parts_of_annotation.text
                else:
                    raise UnsupportedXsdTagError("annotation", _local_tag(parts_of_annotation))
        elif _local_tag(parts_of_schema) == "complexType":
            # complex type name
            complex_type_name = parts_of_schema.get("name")
            classes[complex_type_name] = {}
            classes[complex_type_name]["attributes"] = {}
            for parts_of_complex_type in parts_of_schema:
                if _local_tag(parts_of_complex_type) == "annotation":
                    for parts_of_annotation in parts_of_complex_type:
                        if _local_tag(parts_of_annotation) == "documentation":
                            classes[complex_type_name]["description"] = parts_of_annotation.text
                        elif _local_tag(parts_of_annotation) == "appinfo":
                            for parts_of_appinfo in parts_of_annotation:
                                if _local_tag(parts_of_appinfo) in ("Class", "ObjectProperty", "DataProperty"):
                                    for parts_of_class_objectProperty_DataProperty in parts_of_appinfo:
                                        if _local_tag(parts_of_class_objectProperty_DataProperty) == "exactMatch":
                                            exactMatch = parts_of_class_objectProperty_DataProperty.get(
                                                "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
                                            )
                                            classes[complex_type_name]["exact_mappings"] = [exactMatch]
                                        elif _local_tag(parts_of_class_objectProperty_DataProperty) == "closeMatch":
                                            closeMatch = parts_of_class_objectProperty_DataProperty.get(
                                                "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
                                            )
                                            classes[complex_type_name]["close_mappings"] = [closeMatch]
                                        else:
                                            raise UnsupportedXsdTagError(
                                                "Class/ObjectProperty/DataProperty",
                                                _local_tag(parts_of_class_objectProperty_DataProperty),
                                            )
                                else:
                                    raise UnsupportedXsdTagError("appinfo", _local_tag(parts_of_appinfo))
                        else:
                            raise UnsupportedXsdTagError("annotation", _local_tag(parts_of_annotation))
                elif _local_tag(parts_of_complex_type) == "sequence":
                    for parts_of_sequence in parts_of_complex_type:
                        if _local_tag(parts_of_sequence) == "element":
                            # element name, type
                            element_name = parts_of_sequence.get("name")
                            classes[complex_type_name]["attributes"][element_name] = {}
                            classes[complex_type_name]["attributes"][element_name]["range"] = parts_of_sequence.get(
                                "type"
                            ).split(":")[-1]

                            # element required
                            element_required = (
                                parts_of_sequence.get("minOccurs") == "1" or parts_of_sequence.get("use") == "required"
                            )
                            if element_required:
                                classes[complex_type_name]["attributes"][element_name]["required"] = True

                            # element not required and nillable
                            element_required_nillable = (
                                parts_of_sequence.get("minOccurs") == "0"
                                and parts_of_sequence.get("nillable") is not None
                            )
                            if element_required_nillable:
                                classes[complex_type_name]["attributes"][element_name]["required"] = False

                            # element multiplicity
                            max_occurs = parts_of_sequence.get("maxOccurs")
                            element_multiplicity = max_occurs == "unbounded" or (
                                max_occurs is not None and max_occurs.isdigit() and int(max_occurs) > 1
                            )
                            if element_multiplicity:
                                classes[complex_type_name]["attributes"][element_name]["multivalued"] = True

                            for parts_of_element in parts_of_sequence:
                                # element annotation
                                if _local_tag(parts_of_element) == "annotation":
                                    # element documentation
                                    for parts_of_annotation in parts_of_element:
                                        if _local_tag(parts_of_annotation) == "documentation":
                                            classes[complex_type_name]["attributes"][element_name]["description"] = (
                                                parts_of_annotation.text
                                            )
                                        elif _local_tag(parts_of_annotation) == "appinfo":
                                            # element appinfo
                                            for parts_of_appinfo in parts_of_annotation:
                                                if _local_tag(parts_of_appinfo) in (
                                                    "Class",
                                                    "ObjectProperty",
                                                    "DataProperty",
                                                ):
                                                    for parts_of_class_objectProperty_DataProperty in parts_of_appinfo:
                                                        if (
                                                            _local_tag(parts_of_class_objectProperty_DataProperty)
                                                            == "exactMatch"
                                                        ):
                                                            exactMatch = parts_of_class_objectProperty_DataProperty.get(
                                                                "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
                                                            )
                                                            classes[complex_type_name]["attributes"][element_name][
                                                                "exact_mappings"
                                                            ] = [exactMatch]
                                                        elif (
                                                            _local_tag(parts_of_class_objectProperty_DataProperty)
                                                            == "closeMatch"
                                                        ):
                                                            closeMatch = parts_of_class_objectProperty_DataProperty.get(
                                                                "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
                                                            )
                                                            classes[complex_type_name]["attributes"][element_name][
                                                                "close_mappings"
                                                            ] = [closeMatch]
                                                        else:
                                                            raise UnsupportedXsdTagError(
                                                                "Class/ObjectProperty/DataProperty",
                                                                _local_tag(parts_of_class_objectProperty_DataProperty),
                                                            )
                                                else:
                                                    raise UnsupportedXsdTagError(
                                                        "appinfo", _local_tag(parts_of_appinfo)
                                                    )
                                        else:
                                            raise UnsupportedXsdTagError("annotation", _local_tag(parts_of_annotation))
                                else:
                                    raise UnsupportedXsdTagError("element", _local_tag(parts_of_element))
                        else:
                            raise UnsupportedXsdTagError("sequence", _local_tag(parts_of_sequence))
                elif _local_tag(parts_of_complex_type) == "attribute":
                    # attribute name, type
                    attribute_name = parts_of_complex_type.get("name")
                    classes[complex_type_name]["attributes"][attribute_name] = {}
                    classes[complex_type_name]["attributes"][attribute_name]["range"] = parts_of_complex_type.get(
                        "type"
                    ).split(":")[-1]

                    # keywords
                    classes[complex_type_name]["attributes"][attribute_name]["keywords"] = ["attribute"]

                    # attribute required
                    attribute_required = parts_of_complex_type.get("use") == "required"
                    if attribute_required:
                        classes[complex_type_name]["attributes"][attribute_name]["required"] = True

                    attribute_nillable = (
                        parts_of_complex_type.get("nillable") == "true"
                        or parts_of_complex_type.get("use") == "optional"
                    )
                    if attribute_nillable:
                        classes[complex_type_name]["attributes"][attribute_name]["required"] = False

                    for parts_of_attribute in parts_of_complex_type:
                        if _local_tag(parts_of_attribute) == "annotation":
                            for parts_of_annotation in parts_of_attribute:
                                if _local_tag(parts_of_annotation) == "documentation":
                                    classes[complex_type_name]["attributes"][attribute_name]["description"] = (
                                        parts_of_annotation.text
                                    )
                                else:
                                    raise UnsupportedXsdTagError("annotation", _local_tag(parts_of_annotation))
                        else:
                            raise UnsupportedXsdTagError("attribute", _local_tag(parts_of_attribute))
                elif _local_tag(parts_of_complex_type) == "choice":
                    for parts_of_choice in parts_of_complex_type:
                        if _local_tag(parts_of_choice) == "element":
                            # element name, type
                            element_name = parts_of_choice.get("name")
                            classes[complex_type_name]["attributes"][element_name] = {}
                            classes[complex_type_name]["attributes"][element_name]["range"] = parts_of_choice.get(
                                "type"
                            ).split(":")[-1]
                            # keywords
                            classes[complex_type_name]["attributes"][element_name]["keywords"] = ["choice"]

                            # element required
                            element_required = (
                                parts_of_choice.get("minOccurs") == "1" or parts_of_choice.get("use") == "required"
                            )
                            if element_required:
                                classes[complex_type_name]["attributes"][element_name]["required"] = True

                            # element not required and nillable
                            element_required_nillable = (
                                parts_of_choice.get("minOccurs") == "0" and parts_of_choice.get("nillable") is not None
                            )
                            if element_required_nillable:
                                classes[complex_type_name]["attributes"][element_name]["required"] = False

                            # element multiplicity
                            max_occurs = parts_of_choice.get("maxOccurs")
                            element_multiplicity = max_occurs == "unbounded" or (
                                max_occurs is not None and max_occurs.isdigit() and int(max_occurs) > 1
                            )
                            if element_multiplicity:
                                classes[complex_type_name]["attributes"][element_name]["multivalued"] = True
                            for parts_of_element in parts_of_choice:
                                if _local_tag(parts_of_element) == "annotation":
                                    for parts_of_annotation in parts_of_element:
                                        if _local_tag(parts_of_annotation) == "documentation":
                                            classes[complex_type_name]["attributes"][element_name]["description"] = (
                                                parts_of_annotation.text
                                            )
                                        else:
                                            raise UnsupportedXsdTagError("annotation", _local_tag(parts_of_annotation))
                                else:
                                    raise UnsupportedXsdTagError("element", _local_tag(parts_of_element))
                        else:
                            raise UnsupportedXsdTagError("choice", _local_tag(parts_of_choice))
                elif _local_tag(parts_of_complex_type) == "simpleContent":
                    for parts_of_simple_content in parts_of_complex_type:
                        if _local_tag(parts_of_simple_content) == "extension":
                            # NOTE: the simpleContent extension `base` (the value type) is
                            # intentionally not mapped to `is_a` — only its attributes are kept.
                            for parts_of_extension in parts_of_simple_content:
                                if _local_tag(parts_of_extension) == "attribute":
                                    # attribute name, type
                                    attribute_name = parts_of_extension.get("name")
                                    classes[complex_type_name]["attributes"][attribute_name] = {}
                                    classes[complex_type_name]["attributes"][attribute_name]["range"] = (
                                        parts_of_extension.get("type").split(":")[-1]
                                    )

                                    # attribute required
                                    attribute_required = parts_of_extension.get("use") == "required"
                                    if attribute_required:
                                        classes[complex_type_name]["attributes"][attribute_name]["required"] = True

                                    attribute_nillable = (
                                        parts_of_extension.get("nillable") == "true"
                                        or parts_of_extension.get("use") == "optional"
                                    )
                                    if attribute_nillable:
                                        classes[complex_type_name]["attributes"][attribute_name]["required"] = False
                                    # keywords
                                    classes[complex_type_name]["attributes"][attribute_name]["keywords"] = ["attribute"]

                                    for parts_of_attribute in parts_of_extension:
                                        if _local_tag(parts_of_attribute) == "annotation":
                                            for parts_of_annotation in parts_of_attribute:
                                                if _local_tag(parts_of_annotation) == "documentation":
                                                    classes[complex_type_name]["attributes"][attribute_name][
                                                        "description"
                                                    ] = parts_of_annotation.text
                                                else:
                                                    raise UnsupportedXsdTagError(
                                                        "annotation", _local_tag(parts_of_annotation)
                                                    )
                                        else:
                                            raise UnsupportedXsdTagError("attribute", _local_tag(parts_of_attribute))
                                elif _local_tag(parts_of_extension) == "attributeGroup":
                                    # ref attribute group name
                                    ref_complex_type_name = parts_of_extension.get("ref").split(":")[-1]

                                    classes[complex_type_name]["mixins"] = [ref_complex_type_name]

                                    for parts_of_attribute_group in parts_of_extension:
                                        if _local_tag(parts_of_attribute_group) == "annotation":
                                            for parts_of_annotation in parts_of_attribute_group:
                                                if _local_tag(parts_of_annotation) == "documentation":
                                                    # add description to attribute group
                                                    if ref_complex_type_name in classes:
                                                        classes[ref_complex_type_name]["description"] = (
                                                            parts_of_annotation.text
                                                        )
                                                    else:
                                                        classes[ref_complex_type_name] = {}
                                                        classes[ref_complex_type_name]["description"] = (
                                                            parts_of_annotation.text
                                                        )
                                                else:
                                                    raise UnsupportedXsdTagError(
                                                        "annotation", _local_tag(parts_of_annotation)
                                                    )
                                        else:
                                            raise UnsupportedXsdTagError(
                                                "attributeGroup", _local_tag(parts_of_attribute_group)
                                            )
                                else:
                                    raise UnsupportedXsdTagError("extension", _local_tag(parts_of_extension))
                        else:
                            raise UnsupportedXsdTagError("simpleContent", _local_tag(parts_of_simple_content))
                elif _local_tag(parts_of_complex_type) == "complexContent":
                    for parts_of_complex_content in parts_of_complex_type:
                        if _local_tag(parts_of_complex_content) == "extension":
                            # complexContent extension base
                            base = parts_of_complex_content.get("base").split(":")[-1]
                            classes[complex_type_name]["is_a"] = base

                            for parts_of_extension in parts_of_complex_content:
                                if _local_tag(parts_of_extension) == "attribute":
                                    # attribute name, type
                                    attribute_name = parts_of_extension.get("name")
                                    classes[complex_type_name]["attributes"][attribute_name] = {}
                                    classes[complex_type_name]["attributes"][attribute_name]["range"] = (
                                        parts_of_extension.get("type").split(":")[-1]
                                    )

                                    # attribute required
                                    attribute_required = parts_of_extension.get("use") == "required"
                                    if attribute_required:
                                        classes[complex_type_name]["attributes"][attribute_name]["required"] = True

                                    attribute_nillable = (
                                        parts_of_extension.get("nillable") == "true"
                                        or parts_of_extension.get("use") == "optional"
                                    )
                                    if attribute_nillable:
                                        classes[complex_type_name]["attributes"][attribute_name]["required"] = False
                                    # keywords
                                    classes[complex_type_name]["attributes"][attribute_name]["keywords"] = ["attribute"]
                                    for parts_of_attribute in parts_of_extension:
                                        if _local_tag(parts_of_attribute) == "annotation":
                                            for parts_of_annotation in parts_of_attribute:
                                                if _local_tag(parts_of_annotation) == "documentation":
                                                    classes[complex_type_name]["attributes"][attribute_name][
                                                        "description"
                                                    ] = parts_of_annotation.text
                                                else:
                                                    raise UnsupportedXsdTagError(
                                                        "annotation", _local_tag(parts_of_annotation)
                                                    )
                                        else:
                                            raise UnsupportedXsdTagError("attribute", _local_tag(parts_of_attribute))
                                elif _local_tag(parts_of_extension) == "attributeGroup":
                                    # ref attribute group name
                                    ref_complex_type_name = parts_of_extension.get("ref").split(":")[-1]
                                    classes[complex_type_name]["mixins"] = [ref_complex_type_name]

                                    for parts_of_attribute_group in parts_of_extension:
                                        if _local_tag(parts_of_attribute_group) == "annotation":
                                            for parts_of_annotation in parts_of_attribute_group:
                                                if _local_tag(parts_of_annotation) == "documentation":
                                                    # add description to attribute group
                                                    if ref_complex_type_name in classes:
                                                        classes[ref_complex_type_name]["description"] = (
                                                            parts_of_annotation.text
                                                        )
                                                    else:
                                                        classes[ref_complex_type_name] = {}
                                                        classes[ref_complex_type_name]["description"] = (
                                                            parts_of_annotation.text
                                                        )
                                                else:
                                                    raise UnsupportedXsdTagError(
                                                        "annotation", _local_tag(parts_of_annotation)
                                                    )
                                        else:
                                            raise UnsupportedXsdTagError(
                                                "attributeGroup", _local_tag(parts_of_attribute_group)
                                            )
                                else:
                                    raise UnsupportedXsdTagError("extension", _local_tag(parts_of_extension))
                        else:
                            raise UnsupportedXsdTagError("complexContent", _local_tag(parts_of_complex_content))
                elif _local_tag(parts_of_complex_type) == "attributeGroup":
                    # mixin
                    ref_complex_type_name = parts_of_complex_type.get("ref").split(":")[-1]
                    classes[complex_type_name]["mixins"] = [ref_complex_type_name]

                    for parts_of_attribute_group in parts_of_complex_type:
                        if _local_tag(parts_of_attribute_group) == "annotation":
                            for parts_of_annotation in parts_of_attribute_group:
                                if _local_tag(parts_of_annotation) == "documentation":
                                    # add description to attribute group
                                    if ref_complex_type_name in classes:
                                        classes[ref_complex_type_name]["description"] = parts_of_annotation.text
                                    else:
                                        classes[ref_complex_type_name] = {}
                                        classes[ref_complex_type_name]["description"] = parts_of_annotation.text
                                else:
                                    raise UnsupportedXsdTagError("annotation", _local_tag(parts_of_annotation))
                        else:
                            raise UnsupportedXsdTagError("attributeGroup", _local_tag(parts_of_attribute_group))

                else:
                    raise UnsupportedXsdTagError("complexType", _local_tag(parts_of_complex_type))
        elif _local_tag(parts_of_schema) == "simpleType":
            for parts_of_simple_type in parts_of_schema:
                simple_type_name = parts_of_schema.get("name")
                types[simple_type_name] = {}
                # description
                types[simple_type_name]["description"] = "Zložený dátový prvok" + " " + simple_type_name
                if _local_tag(parts_of_simple_type) == "restriction":
                    # base type
                    base = parts_of_simple_type.get("base")
                    types[simple_type_name]["uri"] = base
                    types[simple_type_name]["base"] = base.split(":")[-1]

                    for parts_of_restriction in parts_of_simple_type:
                        if _local_tag(parts_of_restriction) not in ("minLength", "maxLength"):
                            raise UnsupportedXsdTagError("restriction", _local_tag(parts_of_restriction))
        elif _local_tag(parts_of_schema) == "attributeGroup":
            # attribute group name
            attribute_group_name = parts_of_schema.get("name")
            classes[attribute_group_name] = {}
            classes[attribute_group_name]["attributes"] = {}

            # mixin
            classes[attribute_group_name]["mixin"] = True

            for parts_of_attribute_group in parts_of_schema:
                if _local_tag(parts_of_attribute_group) == "annotation":
                    for parts_of_annotation in parts_of_attribute_group:
                        if _local_tag(parts_of_annotation) == "documentation":
                            classes[attribute_group_name]["description"] = parts_of_annotation.text
                        else:
                            raise UnsupportedXsdTagError("annotation", _local_tag(parts_of_annotation))
                elif _local_tag(parts_of_attribute_group) == "attribute":
                    # attribute name, type, keywords
                    attribute_name = parts_of_attribute_group.get("name")
                    classes[attribute_group_name]["attributes"][attribute_name] = {}
                    classes[attribute_group_name]["attributes"][attribute_name]["range"] = parts_of_attribute_group.get(
                        "type"
                    ).split(":")[-1]
                    classes[attribute_group_name]["attributes"][attribute_name]["keywords"] = ["attribute"]

                    # attribute required
                    attribute_required = parts_of_attribute_group.get("use") == "required"
                    if attribute_required:
                        classes[attribute_group_name]["attributes"][attribute_name]["required"] = True

                    attribute_nillable = (
                        parts_of_attribute_group.get("nillable") == "true"
                        or parts_of_attribute_group.get("use") == "optional"
                    )
                    if attribute_nillable:
                        classes[attribute_group_name]["attributes"][attribute_name]["required"] = False

                    for parts_of_attribute in parts_of_attribute_group:
                        if _local_tag(parts_of_attribute) == "annotation":
                            for parts_of_annotation in parts_of_attribute:
                                if _local_tag(parts_of_annotation) == "documentation":
                                    classes[attribute_group_name]["attributes"][attribute_name]["description"] = (
                                        parts_of_annotation.text
                                    )
                                else:
                                    raise UnsupportedXsdTagError("annotation", _local_tag(parts_of_annotation))
                        else:
                            raise UnsupportedXsdTagError("attribute", _local_tag(parts_of_attribute))
                else:
                    raise UnsupportedXsdTagError("attributeGroup", _local_tag(parts_of_attribute_group))

        else:
            raise UnsupportedXsdTagError("schema", _local_tag(parts_of_schema))
    return classes, types


def reorder_dict(d: dict[str, Any], order: list) -> dict[str, Any]:
    def reorder(d):
        if isinstance(d, dict):
            reordered = {k: reorder(d[k]) for k in order if k in d}
            remaining = {k: reorder(v) for k, v in d.items() if k not in reordered}
            reordered.update(remaining)
            return reordered
        return d

    return {k: reorder(v) if isinstance(v, dict) else v for k, v in d.items()}


DEFAULT_KEY_ORDER = [
    "is_a",
    "mixin",
    "description",
    "tree_root",
    "range",
    "exact_mappings",
    "close_mappings",
    "mixins",
    "uri",
    "base",
    "min_length",
    "max_length",
    "required",
    "multivalued",
    "keywords",
    "attributes",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xsd_file", help="Path to the source .xsd schema")
    parser.add_argument("output_file", help="Path to write the generated LinkML .yaml schema to")
    args = parser.parse_args()

    classes, types = parse_xsd(args.xsd_file)
    classes = reorder_dict(classes, DEFAULT_KEY_ORDER)
    types = reorder_dict(types, DEFAULT_KEY_ORDER)

    generate_linkml_yaml(classes, types, args.output_file)


if __name__ == "__main__":
    main()

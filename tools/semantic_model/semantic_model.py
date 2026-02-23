from __future__ import annotations
from os import mkdir
from os.path import exists
from typing import Any, Literal
from pathlib import Path
from json import dump, load
from resources.semantic_model.utils import MODELS_PATH
from rdflib import Graph, RDFS, OWL, RDF, SKOS, URIRef, Literal, XSD
from json import load, dump
from os.path import exists
import uuid
import json

if not exists(MODELS_PATH):
    mkdir(MODELS_PATH)


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ttl_to_uml_json.py
Convert an OWL/RDF ontology in Turtle (TTL) to an Enterprise Architect-like UML JSON.

- Classes (owl:Class)  -> elements of type "uml:Class"
- ObjectProperties     -> connectors of type "Association" (domain -> range)
- DatatypeProperties   -> attributes on the domain class
- rdfs:subClassOf      -> connectors of type "Generalization" (child -> parent)
- owl:Ontology         -> root Package (name from rdfs:label @en if present)

IDs are deterministic per URI (uuid5), prefixed EA-like: EAPK_ for packages, EAID_ for classes.
"""
# ---------- Helpers ----------

def ea_id(prefix: str, uri: str) -> str:
    """
    EA-like deterministic ID from a URI: EAID/EAPK + UUID5 (underscored groups, uppercased).
    """
    u = uuid.uuid5(uuid.NAMESPACE_URL, str(uri))
    s = str(u).replace('-', '_').upper()
    return f"{prefix}_{s}"

def local_name(uri: URIRef) -> str:
    """
    Derive a human-friendly name from a URI: last segment after '/' or '#'.
    """
    s = str(uri)
    if '#' in s:
        s = s.split('#')[-1]
    else:
        s = s.rstrip('/').split('/')[-1]
    return s

def get_label(g: Graph, s: URIRef, lang: str = "en") -> str | None:
    vals = list(g.objects(s, RDFS.label))
    if not vals:
        return None
    # prefer requested language
    for v in vals:
        if isinstance(v, Literal) and v.language == lang:
            return str(v)
    # fallback to first literal/string
    return str(vals[0])

def get_comment(g: Graph, s: URIRef, lang: str = "en") -> str | None:
    vals = list(g.objects(s, RDFS.comment))
    if not vals:
        return None
    for v in vals:
        if isinstance(v, Literal) and v.language == lang:
            return str(v)
    return str(vals[0])

def primitive_from_range(r: URIRef) -> str | None:
    """
    Map RDF/XSD types to UML primitive names; None means treat as classifier name.
    Extend as needed.
    """
    s = str(r)
    if s in (str(RDFS.Literal), str(RDF.langString)):
        return "String"
    # Common XSD mappings
    xsd_map = {
        str(XSD.string): "String",
        str(XSD.boolean): "Boolean",
        str(XSD.integer): "Integer",
        str(XSD.int): "Integer",
        str(XSD.long): "Integer",
        str(XSD.float): "Real",
        str(XSD.double): "Real",
        str(XSD.decimal): "Real",
        str(XSD.date): "Date",
        str(XSD.dateTime): "DateTime",
        str(XSD.time): "Time",
        str(XSD.gYear): "String",       # could be a specialized type
        str(XSD.gYearMonth): "String",
        str(XSD.anyURI): "URI",
    }
    return xsd_map.get(s)

def role_name_from_label(label: str | None) -> str | None:
    """
    EA diagrams often show role names like '+isAbout'. We'll prefix with '+' if label exists.
    """
    if not label:
        return None
    return f"+{label}"

# ---------- Extraction ----------

def extract_ontology_package(g: Graph, custom_name: str | None = None) -> dict:
    # Identify owl:Ontology subject(s)
    ontos = list(g.subjects(RDF.type, OWL.Ontology))
    if ontos:
        onto = ontos[0]
        name = custom_name or get_label(g, onto, "en") or local_name(onto)
        pkg_uri = str(onto)
    else:
        # Fallback package when no owl:Ontology triple is present
        name = custom_name or "Generated"
        pkg_uri = f"urn:pkg:{name}"
    pkg_id = ea_id("EAPK", pkg_uri)
    return {
        "name": name,
        "ID": pkg_id,
        "type": "uml:Package",
        "package": None,  # root has no container, or set to another if desired
        "tags": []  # you can add {"name":"uri","value": pkg_uri} if you need
    }

def build_model(g: Graph, package_name: str | None = None) -> dict:
    model = {"elements": [], "connectors": []}

    # Root package
    root_pkg = extract_ontology_package(g, custom_name=package_name)
    model["elements"].append(root_pkg)
    root_pkg_id = root_pkg["ID"]

    # Index classes for quick lookup
    class_elems: dict[str, dict] = {}

    # 1) Classes
    for cls in g.subjects(RDF.type, OWL.Class):
        uri = str(cls)
        name = get_label(g, cls, "en") or local_name(cls)
        cls_id = ea_id("EAID", uri)
        tags = [{"name": "uri", "value": uri}]
        comment = get_comment(g, cls, "en")
        if comment:
            tags.append({"name": "definition-en", "value": comment})
        label = get_label(g, cls, "en")
        if label:
            tags.append({"name": "label-en", "value": label})
        # Optional: usage scope tag aligned to many SEMIC models
        tags.append({"name": "class-usage-scope", "value": "main"})

        elem = {
            "name": name,
            "ID": cls_id,
            "type": "uml:Class",
            "package": root_pkg_id,
            "tags": tags,
            "attributes": []
        }
        class_elems[uri] = elem
        model["elements"].append(elem)

    # Helper to ensure a class element exists for non-primitive ranges
    def ensure_class(uri_ref: URIRef):
        u = str(uri_ref)
        if u not in class_elems:
            name = get_label(g, uri_ref, "en") or local_name(uri_ref)
            cls_id = ea_id("EAID", u)
            elem = {
                "name": name,
                "ID": cls_id,
                "type": "uml:Class",
                "package": root_pkg_id,
                "tags": [{"name": "uri", "value": u}],
                "attributes": []
            }
            class_elems[u] = elem
            model["elements"].append(elem)
        return class_elems[u]

    # 2) Datatype properties -> attributes
    for prop in g.subjects(RDF.type, OWL.DatatypeProperty):
        prop_uri = str(prop)
        prop_label = get_label(g, prop, "en")
        prop_comment = get_comment(g, prop, "en")
        # domains
        for domain in g.objects(prop, RDFS.domain):
            domain_uri = str(domain)
            if domain_uri not in class_elems:
                # if domain class wasn't declared as owl:Class, still ensure it exists
                ensure_class(domain)
            domain_elem = class_elems[domain_uri]
            # range
            ranges = list(g.objects(prop, RDFS.range)) or [RDFS.Literal]
            for rng in ranges:
                primitive = primitive_from_range(rng)
                if primitive:
                    attr_type = primitive
                else:
                    # Non-primitive (e.g., GenericDate): ensure class and use its name
                    rng_elem = ensure_class(rng)
                    attr_type = rng_elem["name"]

                attr_name = prop_label or local_name(prop)
                attr_tags = [{"name": "uri", "value": prop_uri}]
                if prop_label:
                    attr_tags.append({"name": "label-en", "value": prop_label})
                if prop_comment:
                    attr_tags.append({"name": "definition-en", "value": prop_comment})

                domain_elem["attributes"].append({
                    "name": attr_name,
                    "type": attr_type,
                    # Optional multiplicity defaults (no cardinality info in plain RDFS):
                    "lower": None,
                    "upper": None,
                    "visibility": "public",
                    "tags": attr_tags
                })

    # 3) Object properties -> associations
    for prop in g.subjects(RDF.type, OWL.ObjectProperty):
        prop_uri = str(prop)
        prop_label = get_label(g, prop, "en")
        prop_comment = get_comment(g, prop, "en")

        domains = list(g.objects(prop, RDFS.domain))
        ranges = list(g.objects(prop, RDFS.range))
        # If any side is missing, we cannot create a robust connector
        if not domains or not ranges:
            continue

        for domain in domains:
            domain_elem = ensure_class(domain)
            for rng in ranges:
                range_elem = ensure_class(rng)
                connector = {
                    "source_name": domain_elem["name"],
                    "target_name": range_elem["name"],
                    "relationship": "Association",
                    "lb": None,             # left multiplicity bound (optional)
                    "lt": None,             # left role (optional)
                    "rb": None,             # right multiplicity bound (optional)
                    "rt": role_name_from_label(prop_label),  # right role name
                    "tags": [],
                    "tags_source": [],
                    "tags_target": []
                }
                # Put property metadata under tags_target (as in your example)
                tgt_tags = [{"name": "uri", "value": prop_uri}]
                if prop_comment:
                    tgt_tags.append({"name": "definition-en", "value": prop_comment})
                if prop_label:
                    tgt_tags.append({"name": "label-en", "value": prop_label})
                connector["tags_target"] = tgt_tags
                model["connectors"].append(connector)

    # 4) rdfs:subClassOf -> generalizations
    for child, parent in g.subject_objects(RDFS.subClassOf):
        # skip blank-node restrictions here; focus on named superclass
        if isinstance(parent, URIRef):
            child_elem = ensure_class(child)
            parent_elem = ensure_class(parent)
            gen = {
                "source_name": child_elem["name"],
                "target_name": parent_elem["name"],
                "relationship": "Generalization",
                "lb": None, "lt": None, "rb": None, "rt": None,
                "tags": [], "tags_source": [], "tags_target": []
            }
            model["connectors"].append(gen)

    return model

def _iri_base(iri: str) -> str:
    if not iri or "://" not in iri:
        return None
    # Split on last slash or hash (support both styles)
    for sep in ("/", "#"):
        if sep in iri:
            head, tail = iri.rsplit(sep, 1)
            return head if head else None
    return None

def _label_matches_en(lbl_node: dict[str, Any], expected: str) -> bool:
    return (
        isinstance(lbl_node, dict)
        and lbl_node.get("@language") == "en"
        and lbl_node.get("@value") == expected
    )

    return None

def _find_xmi_class_iri_by_name(model: dict[str, Any], class_name: str) -> str:
    xmi = model.get("xmi", {})
    for el in xmi.get("elements", []):
        if el.get("type") == "uml:Class" and el.get("name") == class_name:
            for t in el.get("tags", []):
                if t.get("name") == "uri":
                    return t.get("value")
    return None

def find_class_by_label(g: Graph, class_label: str):
    for s in g.subjects():
        label = g.value(s, RDFS.label)
        type = g.value(s, RDF.type)
        if label and str(label).lower() == class_label.lower() and str(type) == str(OWL.Class):
            uri = s
            return uri
    return None

def _find_file(
    user: str,
    name: str,
) -> Path:
    return MODELS_PATH/user/f"{name}.json"


def upload_model(
    model: dict[str, Any],
    user: str = "",
    name: str = "",
) -> dict[str, Any]:
    """
    Save a model in JSON format.
    """
    folder_path = MODELS_PATH/user
    if not exists(folder_path):
        mkdir(folder_path)

    with open(_find_file(user, name), "w") as f:
        dump(model, f)

    with open(_find_file(user, name), "r") as f:
        model = load(f)

    return model


def add_class(
    title: str,
    definition: str,
    usage_note: str,
    user: str = "",
    name: str = "",
    package: str = "",
    ID: str = "",
) -> dict[str, Any]:
    """
    Creates a dictionary representing a UML class with associated metadata,
    and adds it to the `user`'s model `name`.

    :param package_id: The ID of the package to which the class belongs.
    :param title: The name of the class.
    :param definition: A textual definition or description of the class.
    :param usage_note: Additional usage notes for the class.
    :return: A dictionary with the following keys:
        - "name": The name of the class (title).
        - "ID": A unique identifier for the class.
        - "type": The UML element type, set to "uml:Class".
        - "package": The ID of the package to which the class belongs.
        - "tags": A list of dictionaries containing metadata tags:
            - "definition": A tag for the class's definition.
            - "label": A tag for the class's label or title.
            - "usage_note": A tag for the class's usage notes.
    """
    fp = _find_file(user, name)
    if not exists(fp):
        return {}
    
    with open(fp, "r") as f:
        model: dict[str, Any] = load(f)

    # --- OWL JSON-LD mode ---
    if "ttl_raw" in model.keys():
        
        # Parse JSON-LD into RDF graph
        g = Graph()
        g.parse(data=model["ttl_raw"], format='turtle')
        # Prevent duplicates by label
        class_uri = find_class_by_label(g, title)
        if class_uri:
            return {"error": "Class already exists"}
        
        new_class_uri = URIRef(ID)
        new_class_label = Literal(title, lang="en")
        new_class_def = Literal(definition, lang="en")
        new_class_usage_note = Literal(usage_note, lang="en")

        g.add((new_class_uri, RDF.type, OWL.Class))  # Declare as owl:Class
        g.add((new_class_uri, RDFS.label, new_class_label))
        g.add((new_class_uri, RDFS.comment, new_class_def))
        g.add((new_class_uri, SKOS.scopeNote, new_class_usage_note))

        # Serialize the graph to JSON-LD (string), then to Python dict
        json_ld_data: str = g.serialize(format="json-ld", indent=4)
        model["ttl"] = json.loads(json_ld_data) if json_ld_data else {}

        ttl_raw_bytes = g.serialize(format="ttl")
        model["ttl_raw"] = ttl_raw_bytes.decode("utf-8") if isinstance(ttl_raw_bytes, (bytes, bytearray)) else str(ttl_raw_bytes)

        model["xmi"] = build_model(g)

        with open(fp, "w") as f:
            dump(model, f)

        with open(fp, "r") as f:
            model = load(f)
            ttl_nodes: list[dict[str, Any]] = model.get("ttl", [])
            return ttl_nodes[-1] if ttl_nodes else {}

    # --- XMI JSON mode (original behavior) ---
    else: 
        element: dict[str, Any] = {
            "name": title,
            "ID": ID,  # _generate_id
            "type": "uml:Class",
            "package": package,
            "tags": [
                {"name": "label", "value": title},
                {"name": "definition", "value": definition},
                {"name": "usage_note", "value": usage_note},
            ],
        }

        if "elements" in model:
            elements: list[dict[str, Any]] = model["elements"]
            elements.append(element)

        with open(fp, "w") as f:
            dump(model, f)

        element.clear()
        with open(fp, "r") as f:
            model = load(f)
            if elements := model.get("elements", []):
                element = model["elements"][-1]

        return element

def add_attribute(
    class_name: str,
    attr_label: str,
    attr_definition: str, 
    attr_uri: str,
    attr_usage_note: str = "", 
    attr_type: str = "",
    user: str = "",
    name: str = "",
) -> dict[str, Any]:
    """
    Adds an attribute to an existing UML class in the model file belonging to `user` and model `name`.

    JSON shape produced:
      {
        "name": "<attr_label>",
        "type": "<attr_type>",
        "lower_bounds": "",            # multiplicities not used; stored as empty strings
        "upper_bounds": "",
        "tags_attribute": [
          { "name": "uri",          "value": "<attr_uri>" },
          { "name": "label-en",     "value": "<attr_label>" },
          { "name": "definition-en","value": "<attr_definition>" },
          { "name": "usageNote-en", "value": "<attr_usage_note>" }
        ]
      }

    Preconditions:
      - The model file path is resolved via `_find_file(user, name)` and must exist.
      - A UML class element with `type == "uml:Class"` and `name == class_name` must exist in `elements`.

    Parameters:
      :param class_name: The exact UML class name in `elements` to which the attribute will be added.
      :param attr_label: The attribute label; also stored as the attribute's `"name"` and in `tags_attribute` as `"label-en"`.
      :param attr_definition: Human-readable definition for the attribute (stored under `"definition-en"`).
      :param attr_uri: URI identifying the attribute (stored under `"uri"` in `tags_attribute`).
      :param attr_usage_note: Optional usage note (stored under `"usageNote-en"`); defaults to empty string.
      :param attr_type: Optional type name for the attribute (e.g., `"Text"`, `"Literal"`, `"GenericDate"`, or a class name).
      :param user: Logical user/tenant identifier used by `_find_file`.
      :param name: Logical model name (file identifier) used by `_find_file`.

    Returns:
      - The stored attribute dictionary (as persisted in the model), or
      - `{"Error": "Model file not found"}` if the model file cannot be resolved, or
      - `{"error": "Class not found"}` if the target class does not exist.

    Side Effects:
      - Persists the updated model to disk (append to `target_class["attributes"]`).
      - Reopens the model and returns the last attribute of the target class to mirror persisted state.
    """

    fp = _find_file(user, name)
    if not exists(fp):
        return {"Error": "Model file not found"}

    with open(fp, "r") as f:
        model: dict[str, Any] = load(f)

# --- JSON-LD mode (OWL)        
    if "ttl_raw" in model.keys():
        
        # Parse JSON-LD into RDF graph
        g = Graph()
        g.parse(data=model["ttl_raw"], format='turtle')
        # Prevent duplicates by label
        class_uri = find_class_by_label(g, class_name)
        if not class_uri:
            return {"error": "Class does not exist"}
        
        new_attribute_uri = URIRef(attr_uri)
        new_attribute_label = Literal(attr_label, lang="en")
        new_attribute_def = Literal(attr_definition, lang="en")
        new_attribute_usage_note = Literal(attr_usage_note, lang="en")

        g.add((new_attribute_uri, RDF.type, OWL.ObjectProperty))  # Declare as owl:ObjectProperty
        g.add((new_attribute_uri, RDFS.label, new_attribute_label))
        g.add((new_attribute_uri, RDFS.comment, new_attribute_def))
        g.add((new_attribute_uri, SKOS.scopeNote, new_attribute_usage_note))
        g.add((new_attribute_uri, RDFS.domain, class_uri))  # Set domain to the class
        # Optionally set range if attr_type corresponds to a known class or primitive
        if attr_type:
            g.add((new_attribute_uri, RDFS.range, URIRef(attr_type)))

        # Serialize the graph to JSON-LD (string), then to Python dict
        json_ld_data: str = g.serialize(format="json-ld", indent=4)
        model["ttl"] = json.loads(json_ld_data) if json_ld_data else {}

        ttl_raw_bytes = g.serialize(format="ttl")
        model["ttl_raw"] = ttl_raw_bytes.decode("utf-8") if isinstance(ttl_raw_bytes, (bytes, bytearray)) else str(ttl_raw_bytes)

        model["xmi"] = build_model(g)

        with open(fp, "w") as f:
            dump(model, f)

        # Reopen & return the persisted node (last in 'ttl')
        with open(fp, "r") as f:
            model = load(f)
            ttl_nodes: list[dict[str, Any]] = model.get("ttl", [])
            return ttl_nodes[-1] if ttl_nodes else {}

    # --- XMI mode (original behavior)
    else: 
        elements: list[dict[str, Any]] = model.get("elements", [])
        # Find the class element by name and type
        target_class: dict[str, Any] = next(
            (el for el in elements if el.get("type") == "uml:Class" and el.get("name") == class_name),
            None
        )
        if not target_class:
            # Class not found; return empty
            return {"error": "Class not found"}

        attribute: dict[str, Any] = {
            "name": attr_label,
            "type": attr_type,
            "lower_bounds": "",
            "upper_bounds": "",
            "tags_attribute": [
                {
                    "name": "uri",
                    "value": attr_uri
                },
                {
                    "name": "label-en",
                    "value": attr_label
                },
                {
                    "name": "definition-en",
                    "value": attr_definition
                },
                {
                    "name": "usageNote-en",
                    "value": attr_usage_note
                }
            ]
        }

        # Ensure attributes array exists
        if "attributes" not in target_class or not isinstance(target_class["attributes"], list):
            target_class["attributes"] = []

        target_class["attributes"].append(attribute)

        with open(fp, "w") as f:
            dump(model, f)

        # Reopen to return the stored copy (mirrors your add_class pattern)
        with open(fp, "r") as f:
            model = load(f)
            elements = model.get("elements", [])
            target_class = next(
                (el for el in elements if el.get("type") == "uml:Class" and el.get("name") == class_name),
                None
            )
            if not target_class:
                return {}
            if target_class.get("attributes"):
                return target_class["attributes"][-1]
            return {}


def add_connector(
    source_name: str,
    target_name: str,
    rel_label: str,
    rel_definition: str, 
    rel_uri: str,
    relationship: str,  # e.g., "Association", "Aggregation", "Composition", "Generalization", "Realization"
    rb: str = None,
    rt: str = None,
    rel_usage_note: str = "",
    user: str = "",
    name: str = "",
) -> dict[str, Any]:
    """
    Adds a connector between two existing elements identified by their names and annotates
    the target end with semantic tags (URI, label, definition, usage note).

    JSON shape produced:
      {
        "source_name": "<source_name>",
        "target_name": "<target_name>",
        "relationship": "<Association|Generalization|...>",
        "lb": null,                 # left-end labels/multiplicities not used by this function
        "lt": null,
        "rb": "<rb or null>",       # right-end multiplicity (e.g., "0..*", "1")
        "rt": "<rt or null>",       # right-end role label (e.g., "+domicile")
        "tags": [],                 # connector-level tags (empty by this function)
        "tags_source": [],          # source-end tags (empty by this function)
        "tags_target": [
          { "name": "uri",          "value": "<rel_uri>" },
          { "name": "label-en",     "value": "<rel_label>" },
          { "name": "definition-en","value": "<rel_definition>" },
          { "name": "usageNote-en", "value": "<rel_usage_note>" }
        ]
      }

    Preconditions:
      - The model file path is resolved via `_find_file(user, name)` and must exist.
      - Elements with `name == source_name` and `name == target_name` must exist in `elements`.

    Parameters:
      :param source_name: Name of the source element (must exist in `elements`).
      :param target_name: Name of the target element (must exist in `elements`).
      :param rel_label: Human-readable role/relationship label stored in `tags_target["label-en"]`.
      :param rel_definition: Definition for the relationship end stored in `tags_target["definition-en"]`.
      :param rel_uri: URI identifying the relationship end stored in `tags_target["uri"]`.
      :param relationship: UML relationship type (e.g., `"Association"`, `"Generalization"`).
      :param rb: Optional right-end multiplicity (e.g., `"0..*"`, `"1"`).
      :param rt: Optional right-end role name (e.g., `"+domicile"`, `"+placeOfBirth"`).
      :param rel_usage_note: Optional usage note for the relationship end stored in `tags_target["usageNote-en"]`.
      :param user: Logical user identifier for `_find_file`.
      :param name: Logical model name (file identifier) for `_find_file`.

    Returns:
      - The stored connector dictionary (as persisted in the model), or
      - `{}` if the model file cannot be resolved or if `source_name`/`target_name` are not found.

    Side Effects:
      - Appends the connector to `model["connectors"]`.
      - Persists the model and returns the last connector to mirror persisted state.
    """

    fp = _find_file(user, name)
    if not exists(fp):
        return {}

    with open(fp, "r") as f:
        model: dict[str, Any] = load(f)

    
# --- JSON-LD mode (OWL)
    if "ttl_raw" in model.keys():
        
        # Parse JSON-LD into RDF graph
        g = Graph()
        g.parse(data=model["ttl_raw"], format='turtle')
        # Prevent duplicates by label
        class_uri = find_class_by_label(g, source_name)
        if not class_uri:
            return {"error": "Class does not exist"}
        
        new_attribute_uri = URIRef(rel_uri)
        new_attribute_label = Literal(rel_label, lang="en")
        new_attribute_def = Literal(rel_definition, lang="en")
        new_attribute_usage_note = Literal(rel_usage_note, lang="en")

        g.add((new_attribute_uri, RDF.type, OWL.ObjectProperty))  # Declare as owl:ObjectProperty
        g.add((new_attribute_uri, RDFS.label, new_attribute_label))
        g.add((new_attribute_uri, RDFS.comment, new_attribute_def))
        g.add((new_attribute_uri, SKOS.scopeNote, new_attribute_usage_note))
        g.add((new_attribute_uri, RDFS.domain, class_uri))  # Set domain to the class

        # Serialize the graph to JSON-LD (string), then to Python dict
        json_ld_data: str = g.serialize(format="json-ld", indent=4)
        model["ttl"] = json.loads(json_ld_data) if json_ld_data else {}

        ttl_raw_bytes = g.serialize(format="ttl")
        model["ttl_raw"] = ttl_raw_bytes.decode("utf-8") if isinstance(ttl_raw_bytes, (bytes, bytearray)) else str(ttl_raw_bytes)

        model["xmi"] = build_model(g)

        with open(fp, "w") as f:
            dump(model, f)

        with open(fp, "r") as f:
            model = load(f)
            ttl_nodes: list[dict[str, Any]] = model.get("ttl", [])
            return ttl_nodes[-1] if ttl_nodes else {}

    # --- XMI mode (original behavior)
    else: 
        elements: list[dict[str, Any]] = model.get("elements", [])

        # Basic existence checks for source and target by name
        src_exists = any(el.get("name") == source_name for el in elements)
        tgt_exists = any(el.get("name") == target_name for el in elements)
        if not (src_exists and tgt_exists):
            return {}

        connector: dict[str, Any] = {
            "source_name": source_name,
            "target_name": target_name,
            "relationship": relationship,
            "lb": None,
            "lt": None,
            "rb": rb if rb is not None else None,
            "rt": rt if rt is not None else None,
            "tags": [],
            "tags_source": [],
            "tags_target": [
                {
                    "name": "uri",
                    "value": rel_uri
                },
                {
                    "name": "label-en",
                    "value": rel_label
                },
                {
                    "name": "definition-en",
                    "value": rel_definition
                },
                {
                    "name": "usageNote-en",
                    "value": rel_usage_note
                }
            ],
        }

        if "connectors" not in model or not isinstance(model["connectors"], list):
            model["connectors"] = []
        model["connectors"].append(connector)

        with open(fp, "w") as f:
            dump(model, f)

        # Reopen to return the stored copy (end of list)
        with open(fp, "r") as f:
            model = load(f)
            connectors: list[dict[str, Any]] = model.get("connectors", [])
            return connectors[-1] if connectors else {}


from __future__ import annotations
from resources.semantic_model.utils import get_model
from tools.style_guide_validator import extract_subgraph_for_uris
from fastmcp import Context
from rdflib import URIRef
from config import load_config
from pathlib import Path
from typing import Any
import pandas as pd
import json
import re

config = load_config()

STYLE_GYDE_XLS_PATH = Path(config["file_paths"]["style_guide_xls"])

df = pd.read_excel(STYLE_GYDE_XLS_PATH, index_col="Rule")
RULES_DICT = df.to_dict(orient="index")

def extract_classes_associations(model: dict[str, Any], names: list[str]) -> dict[str, Any]:
    """
    Extracts classes and associations from the model whose names are in the provided list.

    Args:
        model (dict): The loaded model JSON as a dictionary.
        names (list of str): list of class or association names to extract.

    Returns:
        dict: A dictionary with 'classes' and 'associations' keys containing the matching elements.
    """
    result = {
        "classes": [],
        "associations": []
    }

    # UML XMI JSON
    if "elements" in model and "connectors" in model:
        for element in model.get("elements", []):
            if element.get("type") == "uml:Class" and element.get("name") in names:
                result["classes"].append(element)
        for connector in model.get("connectors", []):
            if (
                connector.get("relationship") == "Association" and
                (connector.get("name") in names or
                 connector.get("source_name") in names or
                 connector.get("target_name") in names)
            ):
                result["associations"].append(connector)
                
    # JSON-LD (ttl key)
    elif "ttl" in model:
        for item in model["ttl"]:
            item_type = item.get("@type", [])
            # Only classes
            if "http://www.w3.org/2002/07/owl#Class" in item_type:
                label = _get_ld_label(item)
                if label and label in names:
                    result["classes"].append(item)
            # Associations: not explicit in JSON-LD, but could be ObjectProperty/DatatypeProperty
            if ("http://www.w3.org/2002/07/owl#ObjectProperty" in item_type or
                "http://www.w3.org/2002/07/owl#DatatypeProperty" in item_type):
                label = _get_ld_label(item)
                if label and label in names:
                    result["associations"].append(item)
    else:
        raise ValueError("Unknown model format: expected UML XMI or JSON-LD with 'ttl' key")

    return result

def metadata_checks(model: dict) -> dict:
    """
    Check if all classes, attributes and associations have the required metadata:
    - URI
    - definition-en
    - label-en
    - usage_note_en

    Returns a dictionary of problematic concepts with their missing metadata.
    """

    if "elements" in model and "connectors" in model:
        # UML XMI JSON
        missing_URI = []
        missing_def = []
        missing_label = []
        missing_usage_note = []

        for element in model["elements"]:
            if element["type"] == 'uml:Class':
                if "uri" not in str(element["tags"]):
                    missing_URI.append(f'Class: {element["name"]}')
                if "definition-en" not in str(element["tags"]):
                    missing_def.append(f'Class: {element["name"]}')
                if "label-en" not in str(element["tags"]):
                    missing_label.append(f'Class: {element["name"]}')
                if "usage_note_en" not in str(element["tags"]):
                    missing_usage_note.append(f'Class: {element["name"]}')

                for attribute in element.get("attributes", []):
                    if "uri" not in str(attribute.get("tags_attribute", {})):
                        missing_URI.append(f'Attribute: {element["name"]}/{attribute["name"]}')
                    if "definition-en" not in str(attribute.get("tags_attribute", {})):
                        missing_def.append(f'Attribute: {element["name"]}/{attribute["name"]}')
                    if "label-en" not in str(attribute.get("tags_attribute", {})):
                        missing_label.append(f'Attribute: {element["name"]}/{attribute["name"]}')
                    if "usage_note_en" not in str(attribute.get("tags_attribute", {})):
                        missing_usage_note.append(f'Attribute: {element["name"]}/{attribute["name"]}')

        for connector in model["connectors"]:
            if connector["relationship"] == 'Association':
                if "uri" not in str(connector.get("tags_target", {})):
                    missing_URI.append(f'Association: {connector["source_name"]}/{connector["rt"]}')
                if "definition-en" not in str(connector.get("tags_target", {})):
                    missing_def.append(f'Association: {connector["source_name"]}/{connector["rt"]}')
                if "label-en" not in str(connector.get("tags_target", {})):
                    missing_label.append(f'Association: {connector["source_name"]}/{connector["rt"]}')
                if "usage_note_en" not in str(connector.get("tags_target", {})):
                    missing_usage_note.append(f'Association: {connector["source_name"]}/{connector["rt"]}')

        return {
            "missing_URI": missing_URI,
            "missing_definition": missing_def,
            "missing_label": missing_label,
            "missing_usage_note": missing_usage_note,
        }

    elif "ttl" in model:
        # JSON-LD (ttl key)
        problematic_concepts = {}

        for item in model["ttl"]:
            item_id = item.get("@id", "")
            item_type = item.get("@type", [])

            if (
                "http://www.w3.org/2002/07/owl#Class" in item_type or
                "http://www.w3.org/2002/07/owl#ObjectProperty" in item_type or
                "http://www.w3.org/2002/07/owl#DatatypeProperty" in item_type
            ):
                if not item_id:
                    problematic_concepts["[no id]"] = ["missing URI"]
                    continue

                issues = []

                if not _get_ld_label(item):
                    issues.append("missing label")
                if not _get_ld_comment(item):
                    issues.append("missing definition")
                if not _get_ld_usage_note(item):
                    issues.append("missing usage note")

                if issues:
                    problematic_concepts[item_id] = issues

        return problematic_concepts

    else:
        raise ValueError("Unknown model format: expected UML XMI or JSON-LD with 'ttl' key")

# --- JSON-LD helpers ---
def _get_ld_label(item):
    # rdfs:label
    labels = item.get("http://www.w3.org/2000/01/rdf-schema#label", [])
    for label in labels:
        if label.get("@language") == "en":
            return label.get("@value")
    if labels:
        return labels[0].get("@value")
    return None

def _get_ld_comment(item):
    # rdfs:comment
    comments = item.get("http://www.w3.org/2000/01/rdf-schema#comment", [])
    for comment in comments:
        if comment.get("@language") == "en":
            return comment.get("@value")
    if comments:
        return comments[0].get("@value")
    return None

def _get_ld_usage_note(item):
    # skos:scopeNote
    notes = item.get("http://www.w3.org/2004/02/skos/core#scopeNote", [])
    for note in notes:
        if note.get("@language") == "en":
            return note.get("@value")
    if notes:
        return notes[0].get("@value")
    return None


async def generate_explanations(rule_description: str, uri: str, sub_graph: str, ctx: Context):
    prompt = {
                "instruction": (
                    "You are a semantic interoperability and ontology expert. "
                    "Your task is to analyze a specific concepts from a user's data model and check whether it violates a specific set of design rules, using the provided context. "
                    "Inputs:\n"
                    "- SEMIC rule description: A plain-language summarry of the SEMIC style guide rule that need to be checked.\n"
                    "- concept: The concept URI that need to be analysed against the rules.\n"
                    "- sub-graph: The RDF triples (in Turtle format) directly relevant to the concept involved.\n"
                    "\n"
                    "Instructions:\n"
                    "1. Clearly identify the potential error and the SEMIC rule it relates to.\n"
                    "2. Explain, in the context of the user's data model (using the sub-graph), what this error means and which concepts are affected.\n"
                    "3. list the concerned concepts (URIs or labels) that are directly involved in the error.\n"
                    "4. Provide a brief, actionable recommendation for how the user can resolve or overcome this error, referencing the SEMIC rule and the sub-graph.\n"
                    "\n"
                    "Output format:\n"
                    "{\n"
                    "  'error': <the error message>,\n"
                    "  'explanation': <what this error means in the context of the user's data model>,\n"
                    "  'concerned_concept': URI or label,\n"
                    "  'resolution': <brief recommendation to fix the error>\n"
                    "}"
                ),
                "SEMIC rule description": rule_description,
                "concept": uri,
                "sub-graph": sub_graph,
            }
    response = await ctx.sample(
        messages=[json.dumps(prompt, ensure_ascii=False, indent=2)],
        system_prompt="You are a semantic interoperability and ontology expert.",
        temperature=0.0,
        max_tokens=600,
    )
    m = re.search(r"\{.*\}", getattr(response, "text", str(response)), re.S)

    return m, response

async def R4_5_7_checks(model: dict[str, Any], ctx: Context):
    
    non_observance_of_GC_R4 = {
            "error": "Non-observance of SEMIC rule GC-R4: The terminology style shall be consistent across the vocabulary.",
            "explanation": RULES_DICT["Non-observance of SEMIC rule GC-R4"]["Description"],
            "concerned_concepts": {},
            "resolution": "See details per concept"
        }
    non_observance_of_GC_R5 = {
            "error": "Non-observance of SEMIC rule GC-R5: The concept definitions shall be elaborated consistently across the vocabulary.",
            "explanation": RULES_DICT["Non-observance of SEMIC rule GC-R5"]["Description"],
            "concerned_concepts": {},
            "resolution": "See details per concept"
        }
    non_observance_of_GC_R7 = {
            "error": "Non-observance of SEMIC rule GC-R7: Indicators of deontic modalities for classes and properties do not have semantic or normative value. Still they may be used as editorial annotations.",
            "explanation": RULES_DICT["Non-observance of SEMIC rule GC-R7"]["Description"],
            "concerned_concepts": {},
            "resolution": "See details per concept"
        }

    if "ttl" in model:        
        # JSON-LD (ttl key)
        for i, item in enumerate(model["ttl"]):
            
            await ctx.report_progress(progress=i, total=len(model["ttl"]))

            if i % 30 == 0 and i > 0:
                await ctx.close_sse_stream()

            item_id = item.get("@id", "")
            item_type = item.get("@type", [])
            # --- OWL Ontology ---
            if ("http://www.w3.org/2002/07/owl#Class" in item_type or 
                "http://www.w3.org/2002/07/owl#ObjectProperty" in item_type or
                "http://www.w3.org/2002/07/owl#DatatypeProperty" in item_type
            ):
                sub_graph = extract_subgraph_for_uris(model["ttl_raw"], [URIRef(item_id)])
                if sub_graph == "\n":
                    sub_graph = model["ttl_raw"]

                m, response = await generate_explanations(RULES_DICT["Non-observance of SEMIC rule GC-R4"]["Description"], item_id, sub_graph, ctx)
                try:
                    non_observance_of_GC_R4["concerned_concepts"][item_id] = json.loads(m.group(0) if m else response.text)
                except Exception:
                    non_observance_of_GC_R4["concerned_concepts"][item_id] = {"llm_output": getattr(response, "text", str(response))}

                m, response = await generate_explanations(RULES_DICT["Non-observance of SEMIC rule GC-R5"]["Description"], item_id, sub_graph, ctx)
                try:
                    non_observance_of_GC_R5["concerned_concepts"][item_id] = json.loads(m.group(0) if m else response.text)
                except Exception:
                    non_observance_of_GC_R5["concerned_concepts"][item_id] = {"llm_output": getattr(response, "text", str(response))}

                m, response = await generate_explanations(RULES_DICT["Non-observance of SEMIC rule GC-R7"]["Description"], item_id, sub_graph, ctx)
                try:
                    non_observance_of_GC_R7["concerned_concepts"][item_id] = json.loads(m.group(0) if m else response.text)
                except Exception:
                    non_observance_of_GC_R7["concerned_concepts"][item_id] = {"llm_output": getattr(response, "text", str(response))}
                    
        return non_observance_of_GC_R4, non_observance_of_GC_R5, non_observance_of_GC_R7
                
    else:
        # Unknown format
        return {"Unknown model format: expected UML XMI or JSON-LD with 'ttl' key"}, {"Unknown model format: expected UML XMI or JSON-LD with 'ttl' key"}, {"Unknown model format: expected UML XMI or JSON-LD with 'ttl' key"}


async def metadata_checker(
    user: str = "",
    name: str = "",
    target_names: list[str] = None,
    check_instruction: str = None,
    ctx: Context = None,
) -> dict:
    """Validate metadata completeness and terminology consistency in a semantic model based on general conventions of the SEMIC style guide."""
    model = get_model(user, name)

    if not target_names:
        non_observance_of_GC_R3 = {
            "error": "Non-observance of SEMIC rule GC-R3: All classes, attributes and associations should have a URI, a definition, a label, and ideally a usage note.",
            "explanation": RULES_DICT["Non-observance of SEMIC rule GC-R3"]["Description"],
            "concerned_concepts": metadata_checks(model),
            "resolution": "Ensure to add a URI, definition, label, and usage note to all classes, attributes, and associations in the model."
        }
        non_observance_of_GC_R4, non_observance_of_GC_R5, non_observance_of_GC_R7 = await R4_5_7_checks(model, ctx)
        
        
        return {
            "Non-observance of SEMIC rule GC-R3: All classes, attributes and associations should have a URI, a definition, a label, and ideally a usage note.": non_observance_of_GC_R3,
            "Non-observance of SEMIC rule GC-R4: The terminology style shall be consistent across the vocabulary.": non_observance_of_GC_R4,
            "Non-observance of SEMIC rule GC-R5: The concept definitions shall be elaborated consistently across the vocabulary.": non_observance_of_GC_R5,
            "Non-observance of SEMIC rule GC-R7: Indicators of deontic modalities for classes and properties do not have semantic or normative value. Still they may be used as editorial annotations.": non_observance_of_GC_R7,
        }
    
    else:
        # Extract subset
        subset = extract_classes_associations(model, target_names)
        # Prepare prompt for LLM
        if not check_instruction:
            check_instruction = (
                "Check the following classes and associations for metadata completeness. "
                "Report any missing or incomplete metadata fields (URI, definition-en, label-en, usage_note_en)."
            )
        prompt = {
            "instruction": check_instruction,
            "data": subset
        }
        if ctx is None:
            raise ValueError("ctx (LLM context) must be provided for targeted checks.")
        # Call LLM
        import json, re
        response = await ctx.sample(
            messages=[json.dumps(prompt, ensure_ascii=False, indent=2)],
            system_prompt="You are a metadata quality checker for semantic models.",
            temperature=0.0,
            max_tokens=800,
        )
        # Try to parse JSON from LLM output
        m = re.search(r"\{.*\}", getattr(response, "text", str(response)), re.S)
        try:
            result = json.loads(m.group(0) if m else response.text)
        except Exception:
            result = {"llm_output": getattr(response, "text", str(response))}
        return result


metadata_checker.__doc__ = f"""
    Validate metadata completeness and terminology consistency in a semantic model based on general conventions of the SEMIC style guide.      

    This tool checks a model (loaded via `get_model(user, name)`) for:
      • GC‑R3 — Metadata completeness (URI, definition, label, usage note)
      • GC‑R4 — Consistent terminology style
      • GC‑R5 — Consistent definition elaboration
      • GC‑R7 — Avoid deontic modality indicators as semantic/normative values

    It supports two modes:

    1) Full model check (default — when `target_names` is None):
       - For UML XMI JSON models (keys: "elements" & "connectors"), it inspects classes, attributes,
         and associations by scanning their tag containers for:
           "uri", "definition-en", "label-en", and "usage_note_en".
       - For JSON‑LD models (key: "ttl"), it inspects OWL Classes and Properties by reading:
           rdfs:label (en), rdfs:comment (en), skos:scopeNote (en), and @id (URI).
       - It returns a structured report for GC‑R3, GC‑R4, GC‑R5, GC‑R7.

    2) Targeted check (when `target_names` is provided):
       - Extracts only the specified classes/associations from the model (UML XMI JSON or JSON‑LD).
       - Sends the extracted subset to an LLM with a custom instruction (`check_instruction`, or a default).
       - Requires `ctx` (LLM context). Returns the LLM's JSON output (or the raw text under "llm_output").

    Supported model formats:
      - UML XMI JSON: expects top-level keys "elements" and "connectors".
      - JSON‑LD: expects top-level key "ttl" (list of JSON‑LD nodes) and "ttl_raw" (Turtle) for R4/R5/R7 checks.

    Args:
        user (str, optional):
            Identifier passed to `get_model` to locate the model. Defaults to "".
        name (str, optional):
            Model name passed to `get_model` to locate the model. Defaults to "".
        target_names (list[str] | None, optional):
            When provided, runs a targeted check for only these class/association names.
            When None, runs the full model check.
        check_instruction (str | None, optional):
            Custom instruction for the LLM in targeted mode. If omitted, a default instruction
            to assess URI/definition/label/usage note completeness is used.
        ctx (Context | None, optional):
            fastmcp Context used to call the LLM. Required for targeted checks.
            In full model mode, ctx is used to generate explanations for GC‑R4/R5/R7.


    Returns:
        dict:
            For full model check:
                - dictionary with four SEMIC rule sections (GC‑R3, GC‑R4, GC‑R5, GC‑R7).
            Each section includes:
              - "error": short rule violation message
              - "explanation": rule description
              - "concerned_concepts": per‑concept findings
              - "resolution": suggested next step

            For targeted check:
                - LLM-generated output, typically a dict describing missing or incomplete metadata for the specified classes/associations.
"""

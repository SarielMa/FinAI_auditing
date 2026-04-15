"""
XBRL Auditing MCP Server

Provides five tools that the auditing agent calls instead of writing
inline Python scripts:

  1. locate_filing       - find the XBRL folder + file paths
  2. extract_xbrl_facts  - parse *_htm.xml → facts + resolved periods
  3. get_calculation_network - parse *_cal.xml → parent/child roles
  4. get_balance_type    - check *.xsd + taxonomy chunks
  5. write_audit_result  - write the final one-line JSON output
"""

import glob
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("xbrl-auditing")

# ---------------------------------------------------------------------------
# Namespace helpers
# ---------------------------------------------------------------------------

XBRL_NS   = "http://www.xbrl.org/2003/instance"
LINK_NS   = "http://www.xbrl.org/2003/linkbase"
XLINK_NS  = "http://www.w3.org/1999/xlink"
XBRLDI_NS = "http://xbrl.org/2006/xbrldi"


def _local(tag: str) -> str:
    """Strip namespace URI from a Clark-notation tag."""
    return tag.split("}")[-1] if "}" in tag else tag


def _norm_concept(raw: str) -> str:
    """Normalize concept id: replace '_' separator after namespace prefix with ':'.

    e.g.  'us-gaap_AssetsCurrent'  →  'us-gaap:AssetsCurrent'
          'us-gaap:AssetsCurrent'  →  unchanged
          'rrr_CustomConcept'      →  'rrr:CustomConcept'
    """
    # href fragments use underscores: 'us-gaap_X' or 'srt_X' or 'rrr_X'
    # We only replace the FIRST underscore when it follows a known ns prefix
    m = re.match(r'^([a-zA-Z][a-zA-Z0-9\-]*)_(.+)$', raw)
    if m:
        prefix, local = m.group(1), m.group(2)
        # if there is already a colon version, keep it; otherwise convert
        return f"{prefix}:{local}"
    return raw


def _concept_local_name(concept_id: str) -> str:
    """Return just the local part: 'us-gaap:AssetsCurrent' → 'AssetsCurrent'."""
    if ":" in concept_id:
        return concept_id.split(":", 1)[1]
    if "_" in concept_id:
        return concept_id.split("_", 1)[1]
    return concept_id


# ---------------------------------------------------------------------------
# Tool 1 — locate_filing
# ---------------------------------------------------------------------------

@mcp.tool()
def locate_filing(data_dir: str, filing_type: str, ticker: str, issue_date: str) -> dict[str, Any]:
    """Locate the XBRL filing folder and return paths to all key files.

    Args:
        data_dir:    Root data directory containing the XBRL subfolder
                     e.g. '/data/auditing'
        filing_type: 'k10' or '10q' (case-insensitive)
        ticker:      Company ticker symbol, e.g. 'rrr' (case-insensitive)
        issue_date:  Filing issue date.  Accepts 'YYYYMMDD' or 'YYYY-MM-DD'.

    Returns:
        {
          "folder":        absolute path to the filing folder,
          "instance_doc":  path to *_htm.xml,
          "cal_xml":       path to *_cal.xml,
          "xsd":           path to *.xsd  (extension schema),
          "def_xml":       path to *_def.xml  (or null),
          "lab_xml":       path to *_lab.xml  (or null),
          "pre_xml":       path to *_pre.xml  (or null),
          "taxonomy_dir":  path to matching gaap_chunks_{year}/ folder
        }
        or {"error": "<message>"} if not found.
    """
    # Normalise inputs
    filing_type = filing_type.lower().replace("-", "")   # '10k' or '10q'
    ticker      = ticker.lower()
    issue_date  = issue_date.replace("-", "")            # → 'YYYYMMDD'

    xbrl_root = os.path.join(data_dir, "XBRL")
    if not os.path.isdir(xbrl_root):
        return {"error": f"XBRL directory not found: {xbrl_root}"}

    # ---- find folder -------------------------------------------------------
    # Preferred: exact match  '{filing_type}-{ticker}-{issue_date}'
    exact = os.path.join(xbrl_root, f"{filing_type}-{ticker}-{issue_date}")
    if os.path.isdir(exact):
        folder = exact
    else:
        # Fuzzy fallback: scan all folders for ticker + date substring
        candidates = [
            d for d in os.listdir(xbrl_root)
            if os.path.isdir(os.path.join(xbrl_root, d))
            and ticker in d.lower()
            and issue_date in d
        ]
        if not candidates:
            # Try matching by filing_type + date only (ticker may differ)
            candidates = [
                d for d in os.listdir(xbrl_root)
                if os.path.isdir(os.path.join(xbrl_root, d))
                and d.startswith(filing_type)
                and issue_date in d
            ]
        if len(candidates) == 1:
            folder = os.path.join(xbrl_root, candidates[0])
        elif len(candidates) > 1:
            return {
                "error": f"Multiple matching folders: {candidates}. "
                         "Please refine ticker or issue_date."
            }
        else:
            return {
                "error": f"No filing folder found for "
                         f"filing_type={filing_type}, ticker={ticker}, "
                         f"issue_date={issue_date} under {xbrl_root}"
            }

    # ---- collect file paths ------------------------------------------------
    def _find_one(pattern: str) -> str | None:
        matches = glob.glob(os.path.join(folder, pattern))
        return matches[0] if matches else None

    instance_doc = _find_one("*_htm.xml")
    cal_xml      = _find_one("*_cal.xml")
    xsd          = _find_one("*.xsd")
    def_xml      = _find_one("*_def.xml")
    lab_xml      = _find_one("*_lab.xml")
    pre_xml      = _find_one("*_pre.xml")

    if not instance_doc:
        return {"error": f"*_htm.xml not found in {folder}"}
    if not cal_xml:
        return {"error": f"*_cal.xml not found in {folder}"}

    # ---- taxonomy dir ------------------------------------------------------
    year = issue_date[:4]
    taxonomy_dir = os.path.join(data_dir, "US_GAAP_Taxonomy", f"gaap_chunks_{year}")
    if not os.path.isdir(taxonomy_dir):
        taxonomy_dir = None

    return {
        "folder":       folder,
        "instance_doc": instance_doc,
        "cal_xml":      cal_xml,
        "xsd":          xsd,
        "def_xml":      def_xml,
        "lab_xml":      lab_xml,
        "pre_xml":      pre_xml,
        "taxonomy_dir": taxonomy_dir,
    }


# ---------------------------------------------------------------------------
# Tool 2 — extract_xbrl_facts
# ---------------------------------------------------------------------------

@mcp.tool()
def extract_xbrl_facts(instance_doc_path: str, concept_local_name: str) -> list[dict[str, Any]]:
    """Extract all reported facts for a concept from the XBRL instance document.

    Args:
        instance_doc_path:   Absolute path to *_htm.xml
        concept_local_name:  Local name only, e.g. 'AssetsCurrent'
                             (strip any namespace prefix before calling)

    Returns:
        List of fact dicts, each with:
          {
            "value":        raw numeric string from the filing,
            "context_id":   contextRef attribute,
            "period_type":  "duration" | "instant",
            "start_date":   "YYYY-MM-DD" or null,
            "end_date":     "YYYY-MM-DD" or null,
            "instant_date": "YYYY-MM-DD" or null,
            "dimensions":   {dimension_name: member_value, ...}  (empty if none)
          }
        Empty list if the concept is not found.
        {"error": "..."} dict in the list on parse failure.
    """
    try:
        tree = ET.parse(instance_doc_path)
    except Exception as e:
        return [{"error": f"Failed to parse {instance_doc_path}: {e}"}]

    root = tree.getroot()

    # ---- build context lookup ----------------------------------------------
    contexts: dict[str, dict] = {}
    for ctx in root.iter():
        if _local(ctx.tag) != "context":
            continue
        ctx_id = ctx.get("id", "")
        period_node = None
        for child in ctx:
            if _local(child.tag) == "period":
                period_node = child
                break

        period_type  = None
        start_date   = None
        end_date     = None
        instant_date = None

        if period_node is not None:
            for p in period_node:
                lname = _local(p.tag)
                if lname == "instant":
                    period_type  = "instant"
                    instant_date = (p.text or "").strip()
                elif lname == "startDate":
                    period_type = "duration"
                    start_date  = (p.text or "").strip()
                elif lname == "endDate":
                    end_date = (p.text or "").strip()

        # dimensions
        dims: dict[str, str] = {}
        for seg in ctx.iter():
            if _local(seg.tag) == "explicitMember":
                dim = seg.get("dimension", "")
                val = (seg.text or "").strip()
                dims[dim] = val

        contexts[ctx_id] = {
            "period_type":  period_type,
            "start_date":   start_date,
            "end_date":     end_date,
            "instant_date": instant_date,
            "dimensions":   dims,
        }

    # ---- collect facts for the target concept ------------------------------
    results = []
    target_local = concept_local_name  # already stripped

    for elem in root.iter():
        if _local(elem.tag) != target_local:
            continue
        value      = (elem.text or "").strip()
        context_id = elem.get("contextRef", "")
        ctx_info   = contexts.get(context_id, {})

        results.append({
            "value":        value,
            "context_id":   context_id,
            "period_type":  ctx_info.get("period_type"),
            "start_date":   ctx_info.get("start_date"),
            "end_date":     ctx_info.get("end_date"),
            "instant_date": ctx_info.get("instant_date"),
            "dimensions":   ctx_info.get("dimensions", {}),
        })

    return results


# ---------------------------------------------------------------------------
# Tool 3 — get_calculation_network
# ---------------------------------------------------------------------------

@mcp.tool()
def get_calculation_network(cal_xml_path: str, concept_id: str) -> dict[str, Any]:
    """Parse the calculation linkbase and return the concept's role in it.

    Args:
        cal_xml_path:  Absolute path to *_cal.xml
        concept_id:    Concept to look up, e.g. 'us-gaap:AssetsCurrent'
                       (colon form preferred; underscore form also accepted)

    Returns:
        {
          "role":      "parent" | "child" | "both" | "none",
          "as_parent": [                        # populated when role is parent/both
            {
              "role_uri":  "http://...",
              "children":  [{"concept": "us-gaap:X", "weight": 1.0}, ...]
            }, ...
          ],
          "as_child":  [                        # populated when role is child/both
            {
              "role_uri": "http://...",
              "parent":   "us-gaap:ParentConcept",
              "own_weight": -1.0,
              "siblings": [{"concept": "us-gaap:X", "weight": 1.0}, ...]
            }, ...
          ]
        }
    """
    # Normalise to colon form for comparison
    target = _norm_concept(concept_id)
    target_local = _concept_local_name(target)

    try:
        tree = ET.parse(cal_xml_path)
    except Exception as e:
        return {"error": f"Failed to parse {cal_xml_path}: {e}"}

    root = tree.getroot()

    as_parent: list[dict] = []
    as_child:  list[dict] = []

    for calc_link in root.iter():
        if _local(calc_link.tag) != "calculationLink":
            continue
        role_uri = calc_link.get(f"{{{XLINK_NS}}}role", "")

        # Build locator table for this calculationLink: label → concept_id
        loc_table: dict[str, str] = {}
        for loc in calc_link:
            if _local(loc.tag) != "loc":
                continue
            label = loc.get(f"{{{XLINK_NS}}}label", "")
            href  = loc.get(f"{{{XLINK_NS}}}href", "")
            # fragment after '#'
            fragment = href.split("#")[-1] if "#" in href else href
            loc_table[label] = _norm_concept(fragment)

        # Collect all arcs in this role
        arcs: list[dict] = []
        for arc in calc_link:
            if _local(arc.tag) != "calculationArc":
                continue
            from_label = arc.get(f"{{{XLINK_NS}}}from", "")
            to_label   = arc.get(f"{{{XLINK_NS}}}to",   "")
            weight_str = arc.get("weight", "1.0")
            try:
                weight = float(weight_str)
            except ValueError:
                weight = 1.0
            from_concept = loc_table.get(from_label, from_label)
            to_concept   = loc_table.get(to_label,   to_label)
            arcs.append({"from": from_concept, "to": to_concept, "weight": weight})

        # Check if target is a parent (from) in any arc
        children = [
            {"concept": a["to"], "weight": a["weight"]}
            for a in arcs
            if _concept_local_name(a["from"]) == target_local
        ]
        if children:
            as_parent.append({"role_uri": role_uri, "children": children})

        # Check if target is a child (to) in any arc
        parent_arcs = [a for a in arcs if _concept_local_name(a["to"]) == target_local]
        for pa in parent_arcs:
            parent_concept = pa["from"]
            own_weight     = pa["weight"]
            siblings = [
                {"concept": a["to"], "weight": a["weight"]}
                for a in arcs
                if _concept_local_name(a["from"]) == _concept_local_name(parent_concept)
                and _concept_local_name(a["to"])   != target_local
            ]
            as_child.append({
                "role_uri":   role_uri,
                "parent":     parent_concept,
                "own_weight": own_weight,
                "siblings":   siblings,
            })

    if as_parent and as_child:
        role = "both"
    elif as_parent:
        role = "parent"
    elif as_child:
        role = "child"
    else:
        role = "none"

    return {"role": role, "as_parent": as_parent, "as_child": as_child}


# ---------------------------------------------------------------------------
# Tool 4 — get_balance_type
# ---------------------------------------------------------------------------

@mcp.tool()
def get_balance_type(xsd_path: str, taxonomy_dir: str, concept_id: str) -> dict[str, str]:
    """Get the balance type of a concept.

    Checks the filing's extension XSD first (for company-specific concepts),
    then falls back to the US-GAAP taxonomy chunks.

    Args:
        xsd_path:     Absolute path to *.xsd  (extension schema)
        taxonomy_dir: Path to gaap_chunks_{year}/ folder containing
                      chunks_core.jsonl
        concept_id:   e.g. 'us-gaap:AssetsCurrent' or 'rrr:CustomConcept'

    Returns:
        {"balance": "debit" | "credit" | "none", "source": "xsd" | "taxonomy" | "not_found"}
    """
    target = _norm_concept(concept_id)
    target_local = _concept_local_name(target)

    # ---- 1. Check extension XSD first (fast, covers company-specific concepts)
    if xsd_path and os.path.isfile(xsd_path):
        try:
            tree = ET.parse(xsd_path)
            for elem in tree.getroot().iter():
                if _local(elem.tag) == "element":
                    name    = elem.get("name", "")
                    balance = elem.get("xbrli:balance", "") or elem.get("balance", "")
                    if name == target_local and balance:
                        return {"balance": balance.lower(), "source": "xsd"}
        except Exception:
            pass  # fall through to taxonomy

    # ---- 2. Search taxonomy chunks_core.jsonl
    if taxonomy_dir and os.path.isdir(taxonomy_dir):
        core_path = os.path.join(taxonomy_dir, "chunks_core.jsonl")
        if os.path.isfile(core_path):
            with open(core_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cid = obj.get("concept_id", "")
                    # Match by full concept_id or by local name
                    if cid == target or _concept_local_name(cid) == target_local:
                        bal = (obj.get("balance") or "").strip().lower()
                        if bal in ("debit", "credit"):
                            return {"balance": bal, "source": "taxonomy"}
                        return {"balance": "none", "source": "taxonomy"}

    return {"balance": "none", "source": "not_found"}


# ---------------------------------------------------------------------------
# Tool 5 — write_audit_result
# ---------------------------------------------------------------------------

@mcp.tool()
def write_audit_result(
    output_dir: str,
    filename: str,
    extracted_value: str,
    calculated_value: str,
) -> dict[str, str]:
    """Write the final one-line audit result JSON to the output directory.

    Args:
        output_dir:        Directory where the result should be saved,
                           e.g. '/results/auditing'
        filename:          Output filename without extension,
                           e.g. 'claude-code_auditing_10k_rrr_20231231_mr_1_claude-sonnet-4-6'
        extracted_value:   Numeric string exactly as found in the filing
        calculated_value:  Correct expected value string

    Returns:
        {"status": "ok", "path": "<absolute path written>"}
        or {"status": "error", "message": "..."}
    """
    os.makedirs(output_dir, exist_ok=True)

    if not filename.endswith(".json"):
        filename = filename + ".json"

    out_path = os.path.join(output_dir, filename)

    payload = json.dumps(
        {"extracted_value": extracted_value, "calculated_value": calculated_value},
        separators=(",", ":"),
    )

    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(payload + "\n")
    except OSError as e:
        return {"status": "error", "message": str(e)}

    return {"status": "ok", "path": out_path}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()

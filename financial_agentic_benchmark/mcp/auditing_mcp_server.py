import json
import os
import xml.etree.ElementTree as ET
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("auditing")


@mcp.tool()
def audit_xbrl(xml_path: str, concept: str, output_path: str):
    if not os.path.exists(xml_path):
        raise ValueError(f"File not found: {xml_path}")

    tree = ET.parse(xml_path)
    root = tree.getroot()

    extracted = None
    for elem in root.iter():
        if elem.tag.endswith(concept.split(":")[-1]):
            extracted = elem.text
            break

    if extracted is None:
        raise ValueError("Concept not found")

    val = float(extracted)
    result = {
        "extracted_value": str(extracted),
        "calculated_value": str(abs(val))
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(result, f)

    return result


if __name__ == "__main__":
    mcp.run()
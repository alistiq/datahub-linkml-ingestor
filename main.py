"""Generate DataHub metadata change proposals from a LinkML schema and emit them.

Reads the DataHub GMS server address from the DATAHUB_GMS_SERVER environment
variable (see .env.example), defaulting to a local instance.
"""

import argparse
import logging
import os

from datahub.emitter.rest_emitter import DatahubRestEmitter

from datahub_mcp_generator import DatahubMCPGenerator

logging.basicConfig(level=logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schema", help="Path to the LinkML schema (.yaml) to ingest")
    parser.add_argument("--platform", default="WebService", help="DataHub platform name for the dataset")
    parser.add_argument(
        "--properties-definition",
        default="./structured_properties/sk.gov.data-props.yml",
        help="Path to the structured properties definition YAML",
    )
    args = parser.parse_args()

    gms_server = os.environ.get("DATAHUB_GMS_SERVER", "http://localhost:8080")

    emitter = DatahubRestEmitter(gms_server=gms_server, extra_headers={})
    emitter.test_connection()

    sp_generator = DatahubMCPGenerator(
        schema=args.schema,
        platform=args.platform,
        properties_definition=args.properties_definition,
    )
    for mcp in sp_generator.generate():
        emitter.emit(mcp)


if __name__ == "__main__":
    main()

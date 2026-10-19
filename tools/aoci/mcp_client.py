"""Local JSON-RPC transport for diagnosing the project's AOCI stdio server.

This does not implement AOCI's authoring workflow. Tool names, arguments and
continuations must come from the live server's schemas and Guide.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
from pathlib import Path
from queue import Empty, Queue
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("method", choices=("tools/list", "tools/call", "interactive"))
    parser.add_argument("--tool")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    if options.method == "tools/call" and not options.tool:
        parser.error("--tool is required for tools/call")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    runtime = ROOT / "tools" / "aoci" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "mcp-stderr.log").open("a", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            [str(ROOT / "tools" / "aoci" / "aoci.exe"), "--repo", str(ROOT), "mcp"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        responses: Queue[str | None] = Queue()

        def read_lines() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                responses.put(line)
            responses.put(None)

        threading.Thread(target=read_lines, daemon=True).start()
        serial = 0

        def request(method: str, params: dict[str, Any]) -> dict[str, Any]:
            nonlocal serial
            serial += 1
            assert process.stdin is not None
            process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": serial,
                                           "method": method, "params": params}) + "\n")
            process.stdin.flush()
            while True:
                try:
                    line = responses.get(timeout=90)
                except Empty as exc:
                    raise RuntimeError("AOCI MCP response timed out") from exc
                if line is None:
                    raise RuntimeError("AOCI MCP exited before returning a response")
                response = json.loads(line)
                if response.get("id") == serial:
                    return response

        try:
            initialized = request("initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "barcode-aoci-diagnostic", "version": "1.0"},
            })
            if "error" in initialized:
                raise RuntimeError(json.dumps(initialized["error"]))
            assert process.stdin is not None
            process.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
            process.stdin.flush()
            if options.method == "interactive":
                print(json.dumps({"initialized": initialized["result"]}, ensure_ascii=False), flush=True)
                for line in sys.stdin:
                    if line.strip() == "exit":
                        break
                    specification = json.loads(line)
                    response = request(specification["method"], specification.get("params", {}))
                    print(json.dumps(response, ensure_ascii=False), flush=True)
                return
            params = {}
            if options.method == "tools/call":
                arguments = json.loads(options.input.read_text(encoding="utf-8-sig")) if options.input else {}
                params = {"name": options.tool, "arguments": arguments}
            response = request(options.method, params)
            serialized = json.dumps(response, ensure_ascii=False, indent=2)
            if options.output:
                output = options.output.resolve()
                if not output.is_relative_to(ROOT):
                    raise ValueError("Diagnostic output must stay inside BarcodeLabelGen")
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(serialized + "\n", encoding="utf-8")
                print(json.dumps({"output": str(output), "isError": response.get("result", {}).get("isError", False),
                                  "error": response.get("error")}, ensure_ascii=False))
            else:
                print(serialized)
        finally:
            if process.stdin:
                process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()

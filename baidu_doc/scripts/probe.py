"""
Phase 1 probe script — validates Baidu Agent Sandbox connectivity.
Run: python baidu_doc/scripts/probe.py
"""
import os
import sys

API_KEY = os.getenv("BAIDU_SANDBOX_API_KEY", "")
if not API_KEY:
    print("ERROR: set BAIDU_SANDBOX_API_KEY env var first")
    sys.exit(1)

os.environ["E2B_API_KEY"] = API_KEY
os.environ["E2B_DOMAIN"] = "agent-sandbox.baidu-int.com"

from e2b_code_interpreter import Sandbox

TEMPLATES = ["code-agent", "code", "fullstack", "browser"]

def probe_template(template: str):
    print(f"\n[{template}] creating sandbox...")
    try:
        sbx = Sandbox(template=template, timeout=120)
        print(f"[{template}] sandbox_id={sbx.sandbox_id}")
        print(f"[{template}] preview url: https://8080-{sbx.sandbox_id}.agent-sandbox.baidu-int.com")

        result = sbx.commands.run("echo hello && uname -a")
        print(f"[{template}] command output: {result.stdout.strip()}")

        sbx.kill()
        print(f"[{template}] killed OK")
        return True
    except Exception as e:
        print(f"[{template}] FAILED: {e}")
        return False

if __name__ == "__main__":
    template = sys.argv[1] if len(sys.argv) > 1 else "code-agent"
    ok = probe_template(template)
    sys.exit(0 if ok else 1)

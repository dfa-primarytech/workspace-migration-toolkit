"""Fail on secrets in tracked/new source files without printing their values."""
import json
import subprocess
import sys

files = subprocess.check_output(  # nosec B603 B607 -- fixed arguments
    ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
).decode().split("\0")
result = subprocess.run(  # nosec B603 -- filenames are separate arguments after --
    [sys.executable, "-m", "detect_secrets", "scan", "--", *sorted(set(f for f in files if f))],
    check=True, capture_output=True, text=True,
)
findings = json.loads(result.stdout)["results"]
if findings:
    for path, items in findings.items():
        print("Secret scan requires review: " + path + " lines " + ",".join(str(i["line_number"]) for i in items))
    sys.exit(1)
print("Secret scan passed.")

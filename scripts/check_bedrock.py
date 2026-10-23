"""Check your Amazon Bedrock setup for ORION's optional voice polish.

    export ORION_BEDROCK_MODEL_ID=<a model ID or inference profile you can use>
    export AWS_REGION=us-east-1
    pip install boto3
    python scripts/check_bedrock.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

model = os.environ.get("ORION_BEDROCK_MODEL_ID")
region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"

print(f"model  : {model or '(ORION_BEDROCK_MODEL_ID not set)'}")
print(f"region : {region}")

if not model:
    sys.exit("\nSet ORION_BEDROCK_MODEL_ID first (copy a model ID from the Bedrock console).")

try:
    import boto3
except ImportError:
    sys.exit("\nboto3 is not installed: pip install boto3")

try:
    identity = boto3.client("sts", region_name=region).get_caller_identity()
    print(f"aws    : authenticated as {identity['Arn']}")
except Exception as error:
    sys.exit(f"\nAWS credentials problem: {error}\n"
             "Run `aws configure` or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.")

from briefing import polish_for_voice  # noqa: E402

sample = "Good morning. You have 3 pending tasks. Your top priority is DBMS Assignment, due Tomorrow."
text, polished = polish_for_voice(sample)

print(f"\ninput    : {sample}")
print(f"output   : {text}")
if polished:
    print("\nOK: Bedrock rewrote the message. Voice polish is working.")
else:
    sys.exit("\nBedrock did not return a usable rewrite (see the warning above). Check that "
             "model access is enabled for this model/region and your IAM user may call "
             "bedrock:InvokeModel.")

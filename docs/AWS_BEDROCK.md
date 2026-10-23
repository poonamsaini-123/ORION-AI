# Enabling the AWS Builder challenge (Amazon Bedrock voice polish)

ORION already contains the integration (`backend/briefing.py`, `polish_for_voice`). It only counts for the *AWS Builder* mini challenge if it is **actually running and shown in your demo**, and described in your feedback answer. Budget about an hour.

1. **AWS account**: sign in to the AWS console and pick a region that offers Bedrock (for example `us-east-1`).
2. **Model access**: Bedrock console → *Model access* (or the model catalog) → request/enable a text model. Copy its **model ID** (or *inference profile ID* if your region requires one).
3. **Credentials**: create an IAM user or role allowed to call `bedrock:InvokeModel`, and either run `aws configure` locally or set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` on your host. Prefer a least-privilege policy and never commit keys.
4. **Install and check**:
   ```bash
   pip install boto3
   export ORION_BEDROCK_MODEL_ID=<your model id>
   export AWS_REGION=us-east-1
   python scripts/check_bedrock.py
   ```
   You should see `OK: Bedrock rewrote the message.`
5. **Run ORION with it**: start the server with the same variables. Calls to `get_daily_briefing(voice_polish=true)`, `what_should_i_do_now(voice_polish=true)`, and the web UI's briefing and plan now return Bedrock-rephrased `spoken` text. The response field `polished: true` confirms it.
6. **Show it in the video**: run `python demo/mcp_demo.py` and point out the `polished` flag, or call the tool in the MCP Inspector.
7. **Document it** in the feedback answer: which service (Amazon Bedrock, Converse API), which model, what you used it for (rewriting spoken summaries), and how it behaved. ORION rejects any rewrite that drops a number and falls back to the built-in text on any error.

Cost note: each call is a short prompt (about 250 output tokens at most). Remove the model access / keys when you are done.

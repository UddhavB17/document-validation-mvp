I want to add an optional remote LLM-based document classification step to our existing pipeline, using a remote Ollama endpoint over LAN. This must be strictly additive — do not modify or remove our existing (deterministic/rule-based) classification logic.
Requirements:
1. Health check before use
Before attempting classification, check if the remote Ollama endpoint (http://192.168.31.225:11434) is reachable, with a short timeout (e.g. 2-3 seconds) — don't let this block or slow down the pipeline if the server is down or unreachable.
2. Fallback behavior

If the Ollama endpoint is unreachable, times out, or returns an error: log/print a clear message like "Local LLM (remote Ollama) not available — continuing with standard classification" and continue using our existing classification logic exactly as it currently works. Do not fail, retry endlessly, or block the pipeline.
If the Ollama endpoint is reachable: use it as an additional classification signal (see below), but our existing deterministic classification should still run — this is a supplement, not a replacement.

3. What to send to Ollama
Feed the already-extracted structured JSON data (from our OCR/extraction pipeline — inspect the current pipeline to find the right stage/variable this JSON is available at) into a prompt asking the model (qwen2.5:7b-instruct-q4_0) to identify what type of document this is, based on the structured fields/content present. Show me the exact prompt template you plan to use before finalizing it, so I can review the wording.
4. Combine results sensibly

If our deterministic classifier and the Ollama result agree, proceed normally.
If they disagree, decide (and tell me your reasoning) whether to: trust the deterministic result by default (safer given our existing accuracy work), or flag it for review. I'd lean toward "deterministic result wins, but log the disagreement for review" — implement it this way unless you see a strong reason not to.
Log every case where Ollama's classification differs from our existing classifier's result (document id, both predictions, timestamp) so we can review these later.

5. Configuration
Make the Ollama endpoint URL and model name configurable (e.g. environment variable or config file), not hardcoded — the IP address may change since this is a LAN-based dev setup, not a permanent server.
6. Timeouts and error handling
Wrap all Ollama calls in proper try/except with the timeout mentioned above. Any exception (connection error, timeout, malformed response, non-200 status) should trigger the same fallback message and continue-as-normal behavior from point 2 — never let an Ollama failure crash or hang the pipeline.
Before implementing, show me:

Where in our current pipeline the classification step happens and where the extracted JSON becomes available
Your planned health-check + timeout logic
The exact prompt template for Ollama

also add option to use local llm on device
Then implement it as an isolated, easily-removable module if possible (e.g. a single file/function we could delete without breaking anything else).
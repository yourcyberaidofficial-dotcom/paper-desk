# Private inference package

This is not a running analyst. No model is installed by this package.

The development host this repository was verified on had 2 CPU cores, about 4 GB RAM, no swap and no GPU. It is below the refusal floor in `ops/inference_host.py` (8 GiB RAM, 4 cores, 20 GiB free disk). That floor stops an accidental download. It is not a measurement of how much RAM Qwen uses once loaded.

## What was not done

- No pull of `qwen3.5:9b-q4_K_M`, `qwen3.5:4b-q4_K_M`, or `qwen3.5:2b-q4_K_M`.
- No purchase of hardware or cloud capacity.
- No publish of port 11434 on a public address.
- No claim that a catalogue file size is the runtime memory requirement.

## When a dedicated host exists

1. Measure RAM, cores, GPU, VRAM, free disk, and swap on that machine. Write the numbers down before any pull.
2. Start only `deploy/private-inference/ollama-loopback.compose.yml`. Confirm from another machine that port 11434 is closed, and from the host that `http://127.0.0.1:11434/api/tags` answers.
3. Pull one candidate, the 9B Q4 first if the measured free RAM and disk can hold the load. Do not pull the 4B or 2B model in the same pass unless the 9B measurement failed and the reason is recorded.
4. Point the desk at `OLLAMA_BASE_URL=http://127.0.0.1:11434` and `OLLAMA_MODEL` set to the tag that was actually loaded. The desk refuses public hosts and cloud model names.
5. Run `ops/test_ai_eval.py` against that live model. A fake transport result is not an acceptance test. The analyst stays `not_operational` until those cases pass.

The desk keeps one inference in flight, drops extra calls as busy, clips the evidence prompt, and limits the reply with `num_predict`. A model outage does not stop the signal engine.

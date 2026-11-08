# Private inference package

This package does not start a model by itself. The refusal floor in `ops/inference_host.py` is unchanged: 8 GiB RAM, 4 cores, 20 GiB free disk. This host is below that floor, so the application still will not download a model on its own.

## Measured on the engineering host, 2026-11-08

The host has no Docker engine and no Docker socket, so `ollama-loopback.compose.yml` was not started. The official Ollama CPU binary 0.40.15 was extracted and bound to `127.0.0.1:11434` only. It is not published on `0.0.0.0`.

Measured before the pull: MemTotal 4024496 kB, no swap, no GPU, about 41 GB disk free. One model was pulled: `qwen2.5:1.5b`, Q4_K_M, 986 MB blob. `qwen2.5:0.5b` was not pulled. Loaded size was 1.1 GB, context 2048, runner llamacpp, size_vram 0. With the model loaded, MemAvailable stayed near 1.6–1.8 GB.

A real `/api/chat` answered. One streaming check on the loaded model: first token 0.506 s, full reply 2.705 s. The customer route `/api/aureon-ai` then returned a validated commentary in 3.937 s (`inference: true`, `approved: false`, `order_opened: false`). Hosted spend stays BLOCKED until `AUREON_AI_API_KEY`, an https `AUREON_AI_BASE_URL`, `AUREON_AI_MODEL`, and `AUREON_AI_SPEND_APPROVED=1` are set. A reply that fails the existing safety checks is not shown. "The chance is VIII." was not accepted.

The production desk network was not visible from this workspace, so this compose file does not declare a Docker network and does not publish port 11434 except on `127.0.0.1`. `http://ollama:11434` is accepted by the allow-list only for a later case where the desk and the model are actually on the same network. That case was not observed. On this host, outside Docker, the address is `http://127.0.0.1:11434`. Do not point a container at loopback and call it the model host.

## What was not done

- No pull of `qwen3.5:9b-q4_K_M`, `qwen3.5:4b-q4_K_M`, or `qwen3.5:2b-q4_K_M`.
- No purchase of hardware or cloud capacity.
- No publish of port 11434 on a public address.
- No claim that a catalogue file size is the runtime memory requirement.
- No claim that the Compose stack is running on this host.

## When a dedicated host exists

1. Measure RAM, cores, GPU, VRAM, free disk, and swap on that machine. Write the numbers down before any pull.
2. Start only `deploy/private-inference/ollama-loopback.compose.yml`. Confirm from another machine that port 11434 is closed, and from the host that `http://127.0.0.1:11434/api/tags` answers.
3. On a host below the refusal floor, do not pull the 9B model. The measured fit on this 3.8 GB host was `qwen2.5:1.5b` Q4_K_M with context 2048 and one request at a time. Pull a second size only if that measurement fails.
4. On the same host, outside Docker, set `OLLAMA_BASE_URL=http://127.0.0.1:11434` and `OLLAMA_MODEL` to the tag that was actually loaded. Do not set `http://ollama:11434` until the desk container and this service are shown to share one network. The desk refuses public hosts and cloud model names. The memory cap in the compose file is 1536M, which covers the measured 1.1 GB load on this 3.8 GB host and leaves room for the desk.
5. A fake transport result is not a live acceptance test.

The desk keeps one inference in flight, drops extra calls as busy, clips the evidence prompt, and limits the reply with `num_predict` 320 and `num_ctx` 2048. A model outage does not stop the signal engine.

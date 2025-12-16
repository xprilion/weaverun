# `weaverun`

Run any application and automatically capture **OpenAI-compatible API traffic** to **Weights & Biases Weave** - without modifying app code.

`weaverun` works as a **process wrapper**: it runs your command, transparently routes only that process’s OpenAI-compatible requests through a local proxy, and logs them to Weave.

---

## What this is for

* Observing LLM calls made by **any app** (Python, Node, etc.)
* Supporting **any OpenAI-compatible provider** (OpenAI, Azure, Together, Groq, vLLM…)
* Capturing requests + responses for **debugging, evals, and tracing**
* Zero application code changes

---

## Install (local dev)

```bash
git clone https://github.com/xprilion/weaverun
cd weaverun
pip install -e .
```

---

## Usage

Run your app exactly as before - just prefix with `weaverun`:

```bash
weaverun python main.py
weaverun pnpm dev
weaverun uvicorn app:app
```

That’s it.

Any OpenAI-compatible API calls made by this process will be logged to **Weave**.

---

## Providers & configuration

`weaverun` respects your existing configuration.

If you already set:

```bash
OPENAI_BASE_URL=https://api.example.com
OPENAI_API_KEY=...
```

`weaverun` will:

* preserve the original provider
* route traffic through a local proxy
* forward requests unchanged

No vendor lock-in. No rewrites.

---

## How it works (high level)

1. `weaverun` starts a **local HTTP proxy**
2. It launches your command as a **child process**
3. It injects environment variables so only that process routes traffic through the proxy
4. The proxy:

   * forwards requests to the original upstream
   * detects OpenAI-compatible APIs by path/schema
   * logs request + response data to Weave

Everything else is passed through untouched.

---

## Safety & best practices

`weaverun` is designed to be safe by default:

* 🔒 **No TLS interception**
* 🔑 **API keys are never modified**
* 🧠 **Only OpenAI-compatible requests are parsed**
* 🔀 **Non-LLM traffic is transparently forwarded**
* 🧪 Scope is limited to the wrapped process only

### Recommended usage

* Use in **local dev, staging, CI, or eval runs**
* Avoid long-running prod usage until redaction rules are configured
* Treat logged prompts/responses as **sensitive data**

---

## Current limitations (MVP)

* Streaming (SSE) responses are logged at request/response level only
* No automatic prompt or PII redaction yet
* No token or cost accounting

These are intentional and will be added incrementally.

---

## License

MIT

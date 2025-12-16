# `weaverun`

Run any application and automatically capture **OpenAI-compatible API traffic** to **Weights & Biases Weave** — without modifying app code.

---

## Install

```bash
pip install weaverun
```

Or from source:
```bash
git clone https://github.com/xprilion/weaverun
cd weaverun
pip install -e .
```

---

## Quick Start

```bash
# Set your Weave project
export WEAVE_PROJECT=your-entity/your-project

# Run your app
weaverun python main.py
```

Output:
```
weaverun: Loaded .env
weaverun: Starting proxy on port 7777...
weaverun: Proxy ready
weaverun: Dashboard: http://127.0.0.1:7777/__weaverun__
weaverun: Running: python main.py
```

---

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `WEAVE_PROJECT` | Weave project (format: `entity/project` or `project`) |
| `WEAVE_PROJECT_ID` | Alternative: just the project ID |
| `WEAVE_ENTITY` | Optional: entity for `WEAVE_PROJECT_ID` |
| `OPENAI_BASE_URL` | Your LLM provider URL (preserved and forwarded) |

weaverun automatically loads `.env` from the current directory.

---

## Dashboard

While your app runs, open the dashboard to see requests in real-time:

```
http://127.0.0.1:7777/__weaverun__
```

Features:
- Live request stream
- Status codes, latency, model
- Click-through to Weave traces

---

## Hardcoded Base URLs

If your app hardcodes `base_url` in the client constructor (e.g., Ollama):

```python
client = OpenAI(base_url="http://localhost:11434/v1", ...)
```

Use `--proxy-all` to route all HTTP traffic through the proxy:

```bash
weaverun --proxy-all python ollama-test.py
```

---

## How It Works

1. Starts a local HTTP proxy
2. Launches your command as a child process
3. Sets `OPENAI_BASE_URL` to route SDK traffic through the proxy
4. Proxy forwards to original upstream and logs OpenAI-compatible calls to Weave

---

## Supported Providers

Any OpenAI-compatible API:
- OpenAI
- Azure OpenAI
- Ollama
- Together, Groq, Fireworks
- vLLM, LiteLLM
- Any OpenAI-compatible endpoint

---

## Safety

- 🔒 No TLS interception
- 🔑 API keys unchanged
- 🧠 Only OpenAI-compatible requests logged
- 🔀 Non-LLM traffic forwarded untouched

---

## License

MIT

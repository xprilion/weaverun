# `weaverun`

Run any application and automatically capture **LLM API traffic** to **Weights & Biases Weave** — without modifying app code.

Supports **OpenAI, Anthropic, Gemini, AWS Bedrock, Azure OpenAI, W&B Inference**, and many more.

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
- Live request stream with SSE support
- Status codes, latency, model, provider badges
- Expandable request/response bodies with syntax highlighting
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

1. Starts a local HTTP proxy with real-time dashboard
2. Launches your command as a child process
3. Sets `OPENAI_BASE_URL` to route SDK traffic through the proxy
4. Proxy forwards to original upstream and logs LLM calls to Weave asynchronously
5. Streaming responses are forwarded in real-time while being captured for logging

---

## Supported Providers

Auto-detected out of the box:

| Provider | Endpoints |
|----------|-----------|
| **OpenAI** | `/v1/chat/completions`, `/v1/embeddings`, etc. |
| **Anthropic** | `/v1/messages`, `/v1/complete` |
| **Google Gemini** | `/v1beta/models/*:generateContent` |
| **AWS Bedrock** | `/model/*/invoke`, `/model/*/converse` |
| **Azure OpenAI** | `/openai/deployments/*/chat/completions` |
| **W&B Inference** | `*.wandb.ai` endpoints |
| **Cohere** | `/v1/chat`, `/v1/generate`, `/v1/embed` |
| **Mistral** | `/v1/chat/completions` |
| **Groq** | `/v1/chat/completions` |
| **Together** | `/v1/chat/completions`, `/inference` |
| **Fireworks** | `/inference/v1/chat/completions` |
| **Perplexity** | `/chat/completions` |
| **Replicate** | `/v1/predictions` |
| **Ollama** | `/api/chat`, `/api/generate` |

---

## Custom Providers

Add your own provider patterns via `weaverun.config.yaml`:

```yaml
providers:
  - name: my_llm
    path_patterns:
      - "/api/v1/generate"
      - "/api/chat"
    host_patterns:
      - "llm\\.mycompany\\.com"
    is_regex: true
```

Config is loaded from:
1. `WEAVERUN_CONFIG` env var
2. `./weaverun.config.yaml`
3. `~/.weaverun.config.yaml`

See `weaverun.config.example.yaml` for full options.

---

## Safety

- 🔒 No TLS interception
- 🔑 API keys unchanged
- 🧠 Only known LLM endpoints logged (configurable)
- 🔀 Non-LLM traffic forwarded untouched
- ⚡ Async logging — zero added latency

---

## License

MIT

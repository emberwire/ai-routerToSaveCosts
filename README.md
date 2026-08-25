# AI-Routed CLI Agent (`ai`)

**Version:** 4.0 (Enterprise AI Systems Architecture)  
**Primary Objective:** Prevent Claude Code and LLM context-window exhaustion and optimize API token spend by automatically intercepting terminal prompts, evaluating intent with Gemini 2.5 Flash, pruning redundant context, routing heavy research to a token-capped n8n pipeline, and dispatching to a pluggable execution engine (**Claude Code**, **Gemini 2.5 Pro/Flash**, **OpenAI Codex / o-series**) with enterprise security guardrails, circuit breaking, and Cloudflare AI Gateway proxying.

---

## 🚀 Quick Start

### 1. Run the Console App
```bash
./run.sh "Build Stripe Checkout webhook handler"
```

### 2. Global `ai` Command Setup
Add this alias to your `~/.zshrc` or `~/.bashrc`:
```bash
alias ai='/Users/arron/.gemini/antigravity/scratch/ai-routed-cli/run.sh'
```

---

## 💡 CLI Usage & Engine Switching

```bash
# 1. Standard Prompt (Automated Intent & n8n research)
ai "Build a Stripe Checkout webhook with HMAC verification"

# 2. Fast-Path Local Edit (<5ms instant bypass)
ai "Fix typo in README.md"

# 3. Route to Gemini (Large context repo analysis / 2M tokens)
ai "Analyze all files in src/ and document architecture" --engine gemini

# 4. Route to Codex / OpenAI (o3-mini / o1 algorithmic reasoning)
ai "Optimize graph dynamic programming algorithm" --engine codex

# 5. Offline Simulation / Demo Mode
ai "Integrate Supabase Auth" --mock

# 6. Force Prep or Bypass Prep
ai "Build payment flow" --no-prep
ai "Explain database indexes" --prep

# 7. Diagnostics (1-Click Health Check)
ai doctor

# 8. ROI & Token Savings Telemetry
ai roi

# 9. Routing Accuracy Benchmark Harness
ai eval

# 10. View & Edit Configuration
ai config
```

---

## 🛡️ CSO Security Guardrails
- **Prompt Injection Quarantine:** Scraped n8n output is quarantined in `<untrusted_external_research_context>` tags with strict anti-RCE execution barriers.
- **Local DLP Scanner:** Regex engine intercepts private keys, JWTs, AWS/GCP tokens, connection strings, and PII *before* network egress.
- **Tamper-Evident Audit Log:** Append-only JSONL log (`~/.ai_router/audit.log`) recording SHA-256 prompt hashes and execution results.

---

## ⚡ CTO Reliability & Fail-Open Resilience
- **Fail-Open Circuit Breaker:** If n8n times out ($>3\text{s}$) or encounters errors, the CLI automatically and silently fails open directly to Claude Code without blocking developer velocity.
- **Session Cache:** Caches latest research in `.ai_router/last_context.md` for instant multi-turn prompt reuse.
- **Cloudflare AI Gateway Proxy:** Built-in normalization for high edge-cache hit ratios and cost tracking.

# 🚀 Semi-Autonomous Software Development Factory

> A control-plane-driven, multi-agent AI system that takes PRDs → specs → code → tests autonomously.

## What is this?
Traditional software development cycles suffer from significant overhead during PM-to-Engineer-to-QA handoffs, leading to disjointed communication and technical drift. We solve this by treating the entire product team as a governed swarm of LLM-based agents (Spec, Code, Test) orchestrated by a centralized state machine. The differentiator is the control plane: rather than agents talking directly and losing track, each agent is rigorously constrained to complete a specific stage under strict MongoDB-persisted state governance.

## Architecture Overview
- **Control Plane**: A FastAPI/Motor async state machine that orchestrates the workflow logic, tracks metrics, and acts as the gatekeeper for artifact promotion.
- **Pipeline**: PRD Ingestion → Specification Generation → Architecture & Code Execution → Test Automation.
- **Agent Hierarchy**: Specialized NVIDIA NIM-powered prompt frameworks dynamically invoked based on pipeline state.

## Quick Start
```bash
# 1. Provide dependencies
pip install -r requirements.txt

# 2. Add Environment variables
cp .env.example .env 
# Add your NVIDIA API tier keys and MONGODB_URI

# 3. Start control-plane & UI dashboard
uvicorn src.api.main:app
```

## Agent Hierarchy

| Agent | Target Model | Role | Tier Priority |
|---|---|---|---|
| SpecGenerator | `qwen/qwen3.5-122b-a10b` | Converts PRDs to structured specifications | Tier 1 |
| CodeGenerator | `qwen/qwen3.5-122b-a10b` | Creates functional architecture / backend | Tier 1 |
| TestGenerator | `mistralai/mistral-small-4-119b-2603` | Creates automated QA pipelines | Tier 2 (Code) |
| Orchestrator | `moonshotai/kimi-k2.5` | Top level flow logic parsing | Tier 2 |
| Validations | `deepseek-ai/deepseek-v3.2`| Structure enforcement checks | Tier 2 |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/prd` | Submit a raw PRD for fully autonomous pipeline generation |
| GET | `/api/v1/executions/{id}` | Poll background execution state and metadata |
| GET | `/api/v1/executions/{id}/artifacts` | Retrieve the generated spec, code, and test artifacts |
| GET | `/api/v1/health` | Validate MongoDB clusters and connectivity ping |
| WS | `/ws` | Subscribe for live multi-agent streaming telemetry |

## Environment Variables

| Variable | Description | Required |
|---|---|---|
| `MONGODB_URI` | Atlas cluster connection string | Yes |
| `MONGODB_DB_NAME` | Database catalog (default: software_factory) | Yes |
| `NVIDIA_API_KEY_QWEN` | NIM Tier 1 primary API Key | Yes |
| `NVIDIA_API_KEY_MISTRAL`| NIM secondary fast tier API Key | Yes |
| `NVIDIA_API_KEY_KIMI` | NIM long-context parsing API Key | No |
| `AGENT_MODE` | Runtime constraint `mock` or `real` | Yes | 

## Tech Stack

| Component | Technology | Why |
|---|---|---|
| Web Framework | FastAPI | Async streaming for LLM tokens and WebSocket IO. |
| Database | MongoDB Atlas | Schemaless document tree naturally maps to unstructured LLM artifacts. |
| DB Driver | Motor | Async wrapper for PyMongo that prevents IO blocking during agent generation. |
| Inference Engine | NVIDIA NIM | Top tier open models distributed natively via fast APIs directly from Nvidia. |

## Known Limitations
* **NVIDIA NIM Rate Limits**: The demo tokens throttle around 40 req/min depending on cluster congestion. Use `asyncio.sleep` bumpers.
* **MongoDB Atlas M0**: Has a strict 512MB storage cap limiting database size and massive PRD archives. Perfect for the initial demo.
* **Probabilistic Determinism**: Agent outputs are not strongly typed statically. The Validation subsystem acts as circuit breakers, but outputs must hit human review before full autonomy.
* **Central Bottleneck**: The FastAPI orchestrator is monolithic in this branch and state-locking can block parallel workflow ingestion.

## Roadmap
1. **Dockerized Agent Runners**: Decoupling the agents into gRPC sidecars instead of direct memory.
2. **Interactive Human Reviews**: Dashboard gates blocking pipeline advancement via the Escalation subsystem.
3. **Advanced AST Validation**: Moving from LLM validation to direct AST/lint execution locally before PRD success.

# VoiceDesk — AI phone agents for businesses

Multi-tenant SaaS: each business signs up, configures one or more AI receptionists, connects a phone
number, and the agent answers calls, answers questions from the business's knowledge base, and books,
moves or cancels appointments. Every business is an isolated organization, so you can sell it per seat,
per agent or per number.

| Part | Stack | Folder |
|---|---|---|
| Dashboard | Next.js 16, React 19, Tailwind 4 | `frontend/` |
| API | FastAPI, Postgres, Redis, Qdrant | `backend/` |
| Background jobs (document ingest, call summaries) | arq | `backend/app/worker.py` |
| Voice worker | LiveKit Agents (Deepgram/OpenAI STT, OpenAI/Gemini LLM, OpenAI/Cartesia TTS) | `agent/` |
| Telephony | Twilio numbers → LiveKit SIP | |

**AI fallback:** each agent has a main model (e.g. `gpt-4o-mini`) and a fallback model
(e.g. `gemini-3.5-flash-flash`). If OpenAI errors or runs out of credits, calls continue on Gemini.

## Run it locally

```bash
cp .env.example .env        # fill in the secrets and API keys
docker compose up --build
docker compose exec api python -m app.seed   # optional demo business + login
```

- Dashboard: http://localhost:3000 (register a new business, or use the seeded login printed above)
- API docs: http://localhost:8000/docs

Without Docker: run Postgres, Redis and Qdrant yourself, then
`cd backend && pip install -r requirements.txt && alembic upgrade head && uvicorn app.main:app --reload`,
`arq app.worker.WorkerSettings`, `cd agent && python -m voice_agent.worker dev`, and `cd frontend && npm run dev`.

## Going live with phone calls

1. Create a LiveKit Cloud project → set `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_SIP_HOST`.
2. Buy a Twilio number → set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`.
3. Set `PUBLIC_BASE_URL` to the public HTTPS URL of the API.
4. Optional outbound calling: `python agent/setup_livekit_sip.py` and copy the trunk id to `LIVEKIT_OUTBOUND_TRUNK_ID`.
5. In the dashboard: **Phone Numbers → Connect number** and choose which agent answers it.

## Deploying (AWS or any cloud)

Every service is a container (`backend/Dockerfile`, `agent/Dockerfile`, `frontend/Dockerfile`).
On AWS a typical setup is ECS Fargate for `api`, `worker`, `agent` and `frontend`; RDS Postgres;
ElastiCache Redis; Qdrant Cloud (or Qdrant on ECS with EFS); an EFS volume for `/data/uploads`; and an
ALB with HTTPS in front of the API and dashboard. Set `ENVIRONMENT=production`.
Build the frontend with `NEXT_PUBLIC_API_URL` set to the public API URL.

## Tests

```bash
cd backend && pytest          # 55 tests, uses SQLite + in-memory Qdrant
cd frontend && npm run build
```

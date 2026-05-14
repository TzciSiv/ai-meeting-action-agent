# AI Meeting Action Agent

A full-stack meeting assistant built with React, TypeScript, FastAPI, SQLite, JWT auth, and OpenAI. It turns a Whisper transcript into private meeting records, action items, direct follow-up answers, and downloadable Word reports.

```text
login -> transcript -> OpenAI summary + action extraction -> SQLite -> React action workflow
```

## Main Features

- Upload meeting audio and fill the transcript field using the Whisper API.
- Opens in a demo workspace automatically, with optional register/login using JWT bearer-token authentication.
- Analyze a meeting transcript with GPT as the default summary model and a separate GPT action extraction call.
- Save each meeting, transcript, summary, follow-up question, follow-up answer, and action board to SQLite.
- View meeting history and reopen saved meetings.
- Add, edit, complete, and delete action items for each meeting.
- Download the transcript as a Word file.
- Download a full Word report that includes current action statuses.

## Project Structure

- `backend/api.py` - FastAPI app and REST routes.
- `backend/auth.py` - password hashing, JWT creation, and token validation.
- `backend/services.py` - analysis, persistence, action CRUD, and export orchestration.
- `backend/models.py` - SQLAlchemy `User`, `Meeting`, and `ActionItem` tables.
- `backend/schemas.py` - API request and response schemas.
- `backend/exports.py` - `.docx` transcript and full-report builders.
- `backend/action_agent.py` - GPT action extraction orchestration, decision detection, and risk detection.
- `backend/llm.py` - Whisper transcription helper and GPT summary, action, and follow-up calls.
- `frontend/src/` - React + TypeScript app.
- `tests/test_backend.py` - API and persistence tests.

## Install

Backend:

```bash
pip install -r requirements.txt
```

Frontend:

```bash
cd frontend
npm install
```

## Run

Start the backend API:

```bash
python -m uvicorn backend.api:app --reload --port 8000
```

Start the frontend:

```bash
cd frontend
npm run dev
```

Open the Vite URL shown in the terminal, usually `http://127.0.0.1:5173`.

## Environment

Create a `.env` file from `.env.example` and set:

```bash
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_TRANSCRIBE_MODEL=whisper-1
OPENAI_SUMMARY_MODEL=gpt-4o-mini
OPENAI_TIMEOUT_SECONDS=120
DATABASE_URL=sqlite:///data/meeting_agent.db
JWT_SECRET_KEY=change_this_to_a_long_random_secret
JWT_EXPIRE_MINUTES=10080
```

The React app expects the API at `http://localhost:8000` by default. To change it, create `frontend/.env`:

```bash
VITE_API_BASE_URL=http://localhost:8000
```

## API Endpoints

- `POST /api/auth/register` - create a user and return a bearer token.
- `POST /api/auth/login` - authenticate a user and return a bearer token.
- `POST /api/auth/demo` - create or reuse the demo user and return a bearer token.
- `GET /api/auth/me` - return the current authenticated user.
- `POST /api/meetings/transcribe` - transcribe an uploaded audio file with Whisper.
- `POST /api/meetings/analyze` - analyze a transcript, save a meeting, and save action items.
- `GET /api/meetings` - list saved meetings.
- `GET /api/meetings/{id}` - get one meeting with summary, transcript, and actions.
- `PATCH /api/meetings/{id}` - rename a saved meeting.
- `POST /api/meetings/{id}/actions` - add an action item to a meeting.
- `PATCH /api/actions/{id}` - edit action task, owner, deadline, evidence, or status.
- `DELETE /api/actions/{id}` - delete an action item.
- `GET /api/meetings/{id}/transcript` - download transcript as `.docx`.
- `GET /api/meetings/{id}/export` - download full meeting report as `.docx`.

## Test

```bash
python -m unittest discover -s tests
python -m py_compile backend/*.py
cd frontend
npm run build
```

## Resume Title

**AI Meeting Action Agent**

## Resume Bullets

- Built a full-stack AI meeting assistant with React, TypeScript, FastAPI, optional JWT auth, SQLAlchemy, SQLite, and OpenAI APIs.
- Designed REST endpoints for authentication, meeting analysis, saved meeting history, action-item CRUD, and Word report exports.
- Implemented an agent workflow that turns meeting transcripts into summaries, decisions, risks, follow-up answers, and GPT-extracted action boards.
- Added direct follow-up answers through the structured meeting summary call, with GPT answering local-model follow-up questions when needed.
- Added persistent action follow-up so users can add, edit, delete, and mark tasks complete after the meeting.
- Generated `.docx` transcript and full-report downloads that reflect current database action statuses.

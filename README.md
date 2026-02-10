# AI Smart Hiring Agent

An autonomous AI agent that automates and improves hiring decisions using local LLM (Ollama).

## Features

- **Resume Parsing**: Extract text from PDF, DOCX, and text files
- **JD Matching Engine**: Compare candidates against job descriptions with weighted scoring
- **Candidate Ranking**: Automatically rank candidates by fit score
- **Risk Detection**: Identify potential risks (job hopping, gaps, shallow expertise)
- **Interview Strategy**: Generate technical, system design, and behavioral questions
- **Hiring Recommendations**: Automated hire/reject/hold decisions with explanations
- **Outlook Ingestion**: Fetch unread Outlook resumes and auto-classify candidates

## Architecture

```
Resume + JD
     ↓
Resume Parser → Skill Extractor
     ↓
JD Matcher → Score Engine
     ↓
Risk Analyzer → Interview Question Generator
     ↓
Decision Engine
     ↓
Actions (Report / Ranking / Alerts)
```

## Tech Stack

- **FastAPI**: REST API framework
- **SQLAlchemy**: Async ORM with SQLite
- **Ollama**: Local LLM for AI analysis
- **LangChain**: LLM orchestration
- **PyPDF / python-docx**: Document parsing

## Prerequisites

1. **Ollama** installed and running:
   ```bash
   # Install Ollama from https://ollama.com
   # Pull a model (e.g., llama3.2)
   ollama pull llama3.2
   ```

2. **Python 3.11+**
3. **DOC parsing dependencies (optional)**: `textract` may require additional system packages for `.doc` files.

## Installation

```bash
# Clone the repository
cd "c:\AI Work\HR Hiring Agent"

# Create virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
copy .env.example .env
```

## Configuration

Edit `.env` to configure:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
API_PORT=8000

# Scoring weights (must sum to 100)
WEIGHT_SKILL_MATCH=40
WEIGHT_EXPERIENCE=25
WEIGHT_DOMAIN_KNOWLEDGE=15
WEIGHT_PROJECT_COMPLEXITY=10
WEIGHT_SOFT_SKILLS=10

# Decision thresholds
THRESHOLD_STRONG_HIRE=80
THRESHOLD_BORDERLINE=60

# Outlook / Microsoft Graph
OUTLOOK_ENABLED=false
OUTLOOK_AUTH_MODE=client_credentials
OUTLOOK_TENANT_ID=
OUTLOOK_CLIENT_ID=
OUTLOOK_CLIENT_SECRET=
OUTLOOK_USER_ID=me
OUTLOOK_SENDER_FILTER=saki.nitin1985@gmail.com
OUTLOOK_MAX_MESSAGES=25
OUTLOOK_ATTACHMENT_DIR=data/outlook_resumes
OUTLOOK_ALLOWED_EXTENSIONS_CSV=.pdf,.doc,.docx
OUTLOOK_DEVICE_SCOPES_CSV=https://graph.microsoft.com/Mail.ReadWrite
```

## Running

```bash
python main.py
```

API will be available at `http://localhost:8000`

## API Endpoints

### Job Descriptions

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/job-descriptions` | Create job description |
| GET | `/job-descriptions` | List all job descriptions |
| GET | `/job-descriptions/{id}` | Get specific job description |
| DELETE | `/job-descriptions/{id}` | Delete job description |

### Candidates

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/candidates` | Create candidate from text |
| POST | `/candidates/upload` | Upload resume file |
| GET | `/candidates` | List candidates |
| GET | `/candidates/{id}` | Get candidate with analysis |
| POST | `/candidates/{id}/analyze` | Analyze candidate |
| DELETE | `/candidates/{id}` | Delete candidate |

### Reports

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/reports/hiring/{jd_id}` | Generate hiring report |
| GET | `/reports/interview-strategy/{candidate_id}` | Get interview strategy |
| GET | `/reports/ranking/{jd_id}` | Get ranked candidates |

### Outlook

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/outlook/ingest` | Ingest unread Outlook resumes |
| GET | `/outlook/candidates` | List Outlook candidates |
| POST | `/outlook/attach` | Attach Outlook candidates to a job description |
| GET | `/outlook/candidates/{id}/resume` | Download Outlook resume |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |

## Example Usage

### 1. Create a Job Description

```bash
curl -X POST "http://localhost:8000/job-descriptions" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Senior Backend Developer",
    "description": "We are looking for a senior backend developer with experience in ASP.NET, SQL, and Azure...",
    "required_skills": ["ASP.NET", "SQL", "Azure", "C#"],
    "min_experience_years": 5,
    "domain": "EHS"
  }'
```

### 2. Upload a Resume

```bash
curl -X POST "http://localhost:8000/candidates/upload" \
  -F "name=John Doe" \
  -F "job_description_id=1" \
  -F "email=john@example.com" \
  -F "file=@resume.pdf"
```

### 3. Analyze Candidate

```bash
curl -X POST "http://localhost:8000/candidates/1/analyze"
```

### 4. Get Hiring Report

```bash
curl "http://localhost:8000/reports/hiring/1"
```

## Scoring System

The agent scores candidates on 5 dimensions:

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Skill Match | 40% | Alignment with required skills |
| Experience | 25% | Years and relevance of experience |
| Domain Knowledge | 15% | Industry/domain expertise |
| Project Complexity | 10% | Scale and complexity of past projects |
| Soft Skills | 10% | Communication, leadership, teamwork |

**Final Score**: Weighted average (0-100)

**Decisions**:
- **Strong Hire** (score ≥ 80): Proceed to interview
- **Borderline** (60-80): Consider if no better candidates
- **Reject** (< 60): Not recommended

## Risk Detection

The agent automatically detects:
- Frequent job changes (stability risk)
- Employment gaps
- Limited project complexity
- Shallow technical depth
- Lack of domain experience
- Limited leadership exposure

## Project Structure

```
hr-hiring-agent/
├── src/
│   ├── agent/              # Core agent logic
│   │   ├── hiring_agent.py
│   │   └── scoring_engine.py
│   ├── api/                # FastAPI application
│   │   ├── app.py
│   │   ├── routers/
│   │   └── schemas.py
│   ├── config/             # Configuration
│   │   └── settings.py
│   ├── database/           # Database models
│   │   ├── connection.py
│   │   └── models.py
│   ├── llm/                # Ollama service
│   │   └── ollama_service.py
│   └── parsers/            # Document parsers
│       └── resume_parser.py
├── main.py                 # Entry point
├── requirements.txt
└── .env.example
```

## License

MIT

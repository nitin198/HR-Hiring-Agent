# AI Smart Hiring Agent - Interactive Web UI

## Overview

The AI Smart Hiring Agent now includes a modern, interactive web UI that allows users to:
- Create and manage job descriptions
- Add candidates and upload resumes
- Analyze candidates using AI-powered scoring
- View hiring reports and interview strategies
- Track candidate rankings
- Download candidate analysis PDFs (single or bulk)

## Features

### Dashboard
- Real-time statistics on job descriptions, candidates, strong hires, and rejects
- Recent candidates list with quick status overview
- Visual indicators for hiring decisions

### Job Descriptions
- Create new job descriptions with:
  - Job title
  - Detailed description
  - Required skills (comma-separated)
  - Minimum experience requirements
  - Domain specification
- View all job descriptions in a list format

### Candidates
- **Add Candidate Tab**: Manually enter candidate details and paste resume text
- **Upload Resume Tab**: Upload resume files (PDF, DOCX, TXT, MD - max 10MB)
- **All Candidates Tab**: View all candidates with:
  - Decision badges (Strong Hire, Borderline, Reject)
  - Total scores
  - Quick actions (Analyze, View, Delete)
  - Download analysis PDFs (single or all candidates as a zip)

### Reports
- **Hiring Report**: Generate comprehensive hiring reports for specific job descriptions
- **Interview Strategy**: Get AI-generated interview strategies with:
  - Focus areas
  - Recommended questions
- **Candidate Rankings**: View ranked list of candidates by score

## Getting Started

### Prerequisites

1. Ensure Ollama is running with the `glm-4.7:cloud` model:
   ```bash
   ollama pull glm-4.7:cloud
   ollama serve
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Running the Application

1. Start the FastAPI server:
   ```bash
   python main.py
   ```

2. Open your browser and navigate to:
   ```
   http://localhost:8000
   ```

The web UI will load automatically.

## Usage Guide

### 1. Create a Job Description

1. Navigate to **Job Descriptions** from the navigation bar
2. Fill in the form:
   - Job Title (required)
   - Description (required)
   - Required Skills (comma-separated)
   - Minimum Experience (years)
   - Domain
3. Click **Create Job Description**

### 2. Add a Candidate

**Option A: Manual Entry**
1. Navigate to **Candidates** → **Add Candidate** tab
2. Fill in the form:
   - Name (required)
   - Email
   - Phone
   - Job Description (required - select from dropdown)
   - Resume Text (required - paste resume content)
3. Click **Add Candidate**

**Option B: Upload Resume**
1. Navigate to **Candidates** → **Upload Resume** tab
2. Fill in the form:
   - Name (required)
   - Email
   - Phone
   - Job Description (required - select from dropdown)
   - Resume File (required - select file)
3. Click **Upload Resume**

### 3. Analyze a Candidate

1. Navigate to **Candidates** → **All Candidates** tab
2. Find the candidate you want to analyze
3. Click the **Analyze** button
4. Wait for the AI analysis to complete
5. The candidate's score and decision will be updated

### 4. View Candidate Details

1. Navigate to **Candidates** → **All Candidates** tab
2. Find the candidate you want to view
3. Click the **View** button
4. A modal will show:
   - Candidate information
   - Resume text
   - Analysis results (if available)
   - Extracted skills
   - Recommendation
   - Risks (if any)

### 5. Generate Reports

**Hiring Report**
1. Navigate to **Reports** section
2. Select a job description from the dropdown
3. Click **Generate Report**
4. View the comprehensive hiring report with statistics

**Interview Strategy**
1. Navigate to **Reports** section
2. Select a job description from the dropdown
3. Click **Generate Strategy**
4. View the interview strategy with focus areas and recommended questions

**Candidate Rankings**
1. Navigate to **Reports** section
2. Select a job description from the dropdown
3. Click **Show Rankings**
4. View the ranked list of candidates

## Scoring System

The AI-powered scoring system evaluates candidates across 5 dimensions:

1. **Skills Match** (20%): Alignment with required skills
2. **Experience Match** (20%): Relevance and depth of experience
3. **Education Match** (20%): Educational background and qualifications
4. **Project Match** (20%): Relevance of past projects
5. **Soft Skills** (20%): Communication, leadership, teamwork

### Decision Thresholds

- **STRONG_HIRE**: Score ≥ 70
- **BORDERLINE**: 50 ≤ Score < 70
- **REJECT**: Score < 50

## Technical Details

### API Endpoints

The UI interacts with the following API endpoints:

- `GET /health` - Health check
- `GET /api/job-descriptions` - List all job descriptions
- `POST /api/job-descriptions` - Create job description
- `GET /api/candidates` - List all candidates
- `POST /api/candidates` - Create candidate
- `POST /api/candidates/upload` - Upload resume
- `GET /api/candidates/{id}` - Get candidate details
- `POST /api/candidates/{id}/analyze` - Analyze candidate
- `DELETE /api/candidates/{id}` - Delete candidate
- `GET /api/reports/hiring/{jd_id}` - Generate hiring report
- `GET /api/reports/interview-strategy/{jd_id}` - Generate interview strategy
- `GET /api/reports/rankings/{jd_id}` - Get candidate rankings

### File Structure

```
static/
├── index.html          # Main UI HTML
└── app.js             # JavaScript application logic
```

### Browser Compatibility

The UI is built with Bootstrap 5 and supports all modern browsers:
- Chrome (latest)
- Firefox (latest)
- Safari (latest)
- Edge (latest)

## Troubleshooting

### UI Not Loading

1. Check that the FastAPI server is running:
   ```bash
   python main.py
   ```

2. Verify the server is accessible at `http://localhost:8000`

3. Check browser console for errors (F12)

### Analysis Not Working

1. Ensure Ollama is running:
   ```bash
   ollama serve
   ```

2. Verify the `glm-4.7:cloud` model is available:
   ```bash
   ollama pull glm-4.7:cloud
   ```

3. Check the health endpoint:
   ```bash
   curl http://localhost:8000/health
   ```

### File Upload Failing

1. Ensure file size is under 10MB
2. Verify file format is supported (PDF, DOCX, TXT, MD)
3. Check browser console for specific error messages

## Security Notes

### CORS Configuration

The current CORS configuration allows all origins (`"*"`). For production deployment, update the CORS settings in `src/api/app.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Replace with your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### File Upload Validation

File uploads are validated for:
- Maximum size: 10MB
- Supported formats: PDF, DOCX, TXT, MD

Additional validation should be added for production use.

## Future Enhancements

Potential improvements for the UI:

1. **Real-time Analysis Progress**: Show progress indicators during AI analysis
2. **Candidate Comparison**: Side-by-side comparison of multiple candidates
3. **Export Reports**: Download reports as PDF or CSV
4. **Dark Mode**: Toggle between light and dark themes
5. **Search and Filtering**: Advanced search and filter capabilities
6. **Candidate Notes**: Add notes and comments to candidates
7. **Interview Scheduling**: Schedule and track interviews
8. **Email Notifications**: Send automated emails to candidates

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the API documentation at `/docs`
3. Check the test results in `TEST_RESULTS.md`
4. Review the main README.md for additional information

## License

This project is part of the AI Smart Hiring Agent system.

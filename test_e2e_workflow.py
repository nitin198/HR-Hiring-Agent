"""End-to-end workflow test with mock data."""

import asyncio
import json
from datetime import datetime
from fastapi.testclient import TestClient
from src.api.app import app
from src.config.settings import get_settings

# Clear the settings cache to reload from .env
get_settings.cache_clear()

# Mock data
MOCK_JOB_DESCRIPTIONS = [
    {
        "title": "Senior Backend Developer",
        "description": """We are looking for a Senior Backend Developer to join our team.

Requirements:
- 5+ years of experience in backend development
- Strong proficiency in Python and FastAPI
- Experience with SQL databases (PostgreSQL, MySQL)
- Knowledge of cloud platforms (AWS, Azure, GCP)
- Experience with microservices architecture
- Strong problem-solving skills
- Experience with CI/CD pipelines
- Knowledge of containerization (Docker, Kubernetes)

Responsibilities:
- Design and implement scalable backend services
- Write clean, maintainable, and well-tested code
- Collaborate with frontend and DevOps teams
- Optimize database queries and application performance
- Participate in code reviews and architectural decisions
- Mentor junior developers""",
        "required_skills": ["Python", "FastAPI", "SQL", "PostgreSQL", "AWS", "Docker", "Kubernetes", "CI/CD"],
        "min_experience_years": 5,
        "domain": "Software Development"
    },
    {
        "title": "Full Stack Developer",
        "description": """We are seeking a Full Stack Developer to build modern web applications.

Requirements:
- 3+ years of full-stack development experience
- Proficiency in React or Vue.js
- Strong backend skills with Node.js or Python
- Experience with RESTful APIs
- Knowledge of database design
- Familiarity with cloud services
- Good understanding of UI/UX principles

Responsibilities:
- Develop and maintain web applications
- Create responsive user interfaces
- Build and consume RESTful APIs
- Collaborate with design team
- Write unit and integration tests""",
        "required_skills": ["React", "Vue.js", "Node.js", "Python", "REST APIs", "SQL", "AWS", "UI/UX"],
        "min_experience_years": 3,
        "domain": "Web Development"
    }
]

MOCK_CANDIDATES = [
    {
        "name": "John Smith",
        "email": "john.smith@example.com",
        "phone": "+1-555-0101",
        "resume_text": """John Smith
Senior Backend Developer
john.smith@example.com | +1-555-0101

SUMMARY
Experienced Senior Backend Developer with 7 years of expertise in building scalable microservices architectures. Proficient in Python, FastAPI, and cloud technologies. Strong track record of delivering high-performance systems.

EXPERIENCE

Senior Backend Developer | TechCorp Inc. | 2020 - Present
- Led development of microservices architecture serving 1M+ users
- Implemented FastAPI-based services with 99.9% uptime
- Optimized database queries reducing response time by 60%
- Designed and implemented CI/CD pipelines using GitHub Actions
- Mentored 3 junior developers

Backend Developer | StartupXYZ | 2018 - 2020
- Built RESTful APIs using Python and Django
- Developed containerized applications with Docker
- Implemented automated testing achieving 90% code coverage
- Collaborated with DevOps to deploy on AWS

Junior Developer | WebAgency | 2017 - 2018
- Developed web applications using Python and Flask
- Worked with PostgreSQL databases
- Participated in agile development processes

SKILLS
- Languages: Python, JavaScript, SQL
- Frameworks: FastAPI, Django, Flask
- Databases: PostgreSQL, MySQL, Redis
- Cloud: AWS (EC2, S3, RDS, Lambda), Azure
- DevOps: Docker, Kubernetes, CI/CD, GitHub Actions
- Tools: Git, Jenkins, Prometheus, Grafana

EDUCATION
Bachelor of Science in Computer Science
State University | 2013 - 2017

CERTIFICATIONS
- AWS Certified Solutions Architect
- Docker Certified Associate""",
        "job_description_id": None  # Will be set dynamically
    },
    {
        "name": "Sarah Johnson",
        "email": "sarah.johnson@example.com",
        "phone": "+1-555-0102",
        "resume_text": """Sarah Johnson
Full Stack Developer
sarah.johnson@example.com | +1-555-0102

SUMMARY
Full Stack Developer with 4 years of experience building modern web applications. Expertise in React, Node.js, and Python. Passionate about creating intuitive user experiences.

EXPERIENCE

Full Stack Developer | DigitalAgency | 2021 - Present
- Developed responsive web applications using React and Node.js
- Built RESTful APIs serving 500K+ users
- Implemented real-time features using WebSockets
- Collaborated with UX designers to improve user experience
- Reduced page load time by 40% through optimization

Frontend Developer | TechStartup | 2019 - 2021
- Created interactive user interfaces with React
- Integrated with backend APIs
- Implemented state management using Redux
- Wrote unit tests using Jest and React Testing Library

Junior Developer | SoftwareCo | 2018 - 2019
- Developed web applications using Vue.js
- Worked with Python backend
- Participated in code reviews and agile ceremonies

SKILLS
- Frontend: React, Vue.js, JavaScript, TypeScript, HTML5, CSS3
- Backend: Node.js, Express, Python, FastAPI
- Databases: PostgreSQL, MongoDB, Redis
- Cloud: AWS, GCP
- Tools: Git, Docker, Jenkins, Webpack

EDUCATION
Bachelor of Science in Software Engineering
Tech University | 2014 - 2018

PROJECTS
- E-commerce Platform: Built full-stack application with React and Node.js
- Task Management App: Developed collaborative tool using React and Python
- Real-time Chat Application: Implemented using WebSockets and Node.js""",
        "job_description_id": None
    },
    {
        "name": "Michael Chen",
        "email": "michael.chen@example.com",
        "phone": "+1-555-0103",
        "resume_text": """Michael Chen
Software Developer
michael.chen@example.com | +1-555-0103

SUMMARY
Software Developer with 2 years of experience. Eager to learn and grow in a challenging environment. Good understanding of web development fundamentals.

EXPERIENCE

Junior Developer | NewTech Co. | 2022 - Present
- Developed web applications using React
- Worked with Node.js backend
- Participated in code reviews
- Learned agile methodologies

Intern | SoftwareCompany | 2021 - 2022
- Assisted in frontend development
- Learned React and JavaScript
- Participated in team meetings

SKILLS
- Frontend: React, JavaScript, HTML, CSS
- Backend: Node.js, Express
- Databases: MongoDB
- Tools: Git, VS Code

EDUCATION
Bachelor of Science in Computer Science
City College | 2018 - 2022

PROJECTS
- Personal Website: Built using React
- Weather App: Developed using JavaScript and APIs""",
        "job_description_id": None
    }
]


def print_section(title):
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_result(test_name, success, details=""):
    """Print test result."""
    status = "[PASS]" if success else "[FAIL]"
    print(f"\n{status}: {test_name}")
    if details:
        print(f"  {details}")


def test_e2e_workflow():
    """Test the complete end-to-end workflow."""
    client = TestClient(app)
    
    print_section("HR HIRING AGENT - END-TO-END WORKFLOW TEST")
    print(f"\nTest started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Track created resources
    job_descriptions = []
    candidates = []
    
    try:
        # ========================================================================
        # STEP 1: Create Job Descriptions
        # ========================================================================
        print_section("STEP 1: Creating Job Descriptions")
        
        for i, jd_data in enumerate(MOCK_JOB_DESCRIPTIONS, 1):
            response = client.post('/api/job-descriptions', json=jd_data)
            if response.status_code == 201:
                jd = response.json()
                job_descriptions.append(jd)
                print_result(
                    f"Created Job Description {i}",
                    True,
                    f"ID: {jd['id']}, Title: {jd['title']}"
                )
            else:
                print_result(
                    f"Created Job Description {i}",
                    False,
                    f"Status: {response.status_code}, Error: {response.text}"
                )
                return False
        
        # ========================================================================
        # STEP 2: Create Candidates
        # ========================================================================
        print_section("STEP 2: Creating Candidates")
        
        # Assign candidates to job descriptions
        MOCK_CANDIDATES[0]["job_description_id"] = job_descriptions[0]["id"]  # John -> Senior Backend
        MOCK_CANDIDATES[1]["job_description_id"] = job_descriptions[1]["id"]  # Sarah -> Full Stack
        MOCK_CANDIDATES[2]["job_description_id"] = job_descriptions[0]["id"]  # Michael -> Senior Backend
        
        for i, candidate_data in enumerate(MOCK_CANDIDATES, 1):
            response = client.post('/api/candidates', json=candidate_data)
            if response.status_code == 201:
                candidate = response.json()
                candidates.append(candidate)
                print_result(
                    f"Created Candidate {i}",
                    True,
                    f"ID: {candidate['id']}, Name: {candidate['name']}, JD ID: {candidate['job_description_id']}"
                )
            else:
                print_result(
                    f"Created Candidate {i}",
                    False,
                    f"Status: {response.status_code}, Error: {response.text}"
                )
                return False
        
        # ========================================================================
        # STEP 3: List All Candidates
        # ========================================================================
        print_section("STEP 3: Listing All Candidates")
        
        response = client.get('/api/candidates')
        if response.status_code == 200:
            all_candidates = response.json()
            print_result(
                "List Candidates",
                True,
                f"Found {len(all_candidates)} candidates total"
            )
            for candidate in all_candidates:
                print(f"  - {candidate['name']} (ID: {candidate['id']})")
        else:
            print_result("List Candidates", False, f"Status: {response.status_code}")
            return False
        
        # ========================================================================
        # STEP 4: Get Candidate Details
        # ========================================================================
        print_section("STEP 4: Getting Candidate Details")
        
        for candidate in candidates:
            response = client.get(f'/api/candidates/{candidate["id"]}')
            if response.status_code == 200:
                data = response.json()
                print_result(
                    f"Get Candidate {candidate['name']}",
                    True,
                    f"Has analysis: {data['analysis'] is not None}"
                )
                if data['analysis']:
                    print(f"  - Skills: {', '.join(data['analysis']['skills'][:5])}...")
                    print(f"  - Experience: {data['analysis']['experience_years']} years")
            else:
                print_result(
                    f"Get Candidate {candidate['name']}",
                    False,
                    f"Status: {response.status_code}"
                )
        
        # ========================================================================
        # STEP 5: Analyze Candidates (if Ollama is available)
        # ========================================================================
        print_section("STEP 5: Analyzing Candidates")
        print("\nNote: This step requires Ollama to be running and may take several minutes...")
        
        for candidate in candidates:
            print(f"\nAnalyzing {candidate['name']}...")
            response = client.post(f'/api/candidates/{candidate["id"]}/analyze')
            
            if response.status_code == 200:
                data = response.json()
                analysis = data['analysis']
                
                if analysis:
                    print_result(
                        f"Analyzed {candidate['name']}",
                        True,
                        f"Score: {analysis['final_score']}/100, Decision: {analysis['decision']}"
                    )
                    print(f"  - Skill Match Score: {analysis['skill_match_score']}")
                    print(f"  - Experience Score: {analysis['experience_score']}")
                    print(f"  - Domain Score: {analysis['domain_score']}")
                    print(f"  - Project Complexity Score: {analysis['project_complexity_score']}")
                    print(f"  - Soft Skills Score: {analysis['soft_skills_score']}")
                    print(f"  - Risk Level: {analysis['risk_level']}")
                    print(f"  - Seniority: {analysis['seniority']}")
                    print(f"  - Strengths: {', '.join(analysis['strengths'][:3])}")
                    print(f"  - Weaknesses: {', '.join(analysis['weaknesses'][:3])}")
                    print(f"  - Risks: {', '.join(analysis['risks'][:3])}")
                else:
                    print_result(
                        f"Analyzed {candidate['name']}",
                        False,
                        "No analysis data returned"
                    )
            else:
                print_result(
                    f"Analyzed {candidate['name']}",
                    False,
                    f"Status: {response.status_code}, Error: {response.text}"
                )
                print("  (This is expected if Ollama is not running)")
        
        # ========================================================================
        # STEP 6: Generate Hiring Report
        # ========================================================================
        print_section("STEP 6: Generating Hiring Reports")
        
        for jd in job_descriptions:
            response = client.get(f'/api/reports/hiring/{jd["id"]}')
            
            if response.status_code == 200:
                report = response.json()
                summary = report['summary']
                
                print_result(
                    f"Hiring Report for {jd['title']}",
                    True,
                    f"Total: {summary['total_candidates']}, Strong Hires: {summary['strong_hires']}, "
                    f"Borderline: {summary['borderline']}, Rejects: {summary['rejects']}"
                )
                print(f"  - Average Score: {summary['average_score']}")
                
                if report['ranked_candidates']:
                    print("\n  Ranked Candidates:")
                    for ranked in report['ranked_candidates'][:3]:
                        print(f"    {ranked['rank']}. Score: {ranked['final_score']}")
            else:
                print_result(
                    f"Hiring Report for {jd['title']}",
                    False,
                    f"Status: {response.status_code}"
                )
        
        # ========================================================================
        # STEP 7: Get Interview Strategy
        # ========================================================================
        print_section("STEP 7: Getting Interview Strategies")
        
        for candidate in candidates:
            response = client.get(f'/api/reports/interview-strategy/{candidate["id"]}')
            
            if response.status_code == 200:
                strategy = response.json()
                interview_strategy = strategy['interview_strategy']
                
                print_result(
                    f"Interview Strategy for {candidate['name']}",
                    True,
                    f"Risk Level: {interview_strategy['risk_level']}"
                )
                print(f"  - Technical Questions: {len(interview_strategy['technical_questions'])}")
                print(f"  - System Design Questions: {len(interview_strategy['system_design_questions'])}")
                print(f"  - Behavioral Questions: {len(interview_strategy['behavioral_questions'])}")
                print(f"  - Focus Areas: {', '.join(interview_strategy['focus_areas'][:3])}")
            else:
                print_result(
                    f"Interview Strategy for {candidate['name']}",
                    False,
                    f"Status: {response.status_code}"
                )
        
        # ========================================================================
        # STEP 8: Get Candidate Rankings
        # ========================================================================
        print_section("STEP 8: Getting Candidate Rankings")
        
        for jd in job_descriptions:
            response = client.get(f'/api/reports/ranking/{jd["id"]}')
            
            if response.status_code == 200:
                ranking = response.json()
                ranked_candidates = ranking['candidates']
                
                print_result(
                    f"Ranking for {jd['title']}",
                    True,
                    f"{len(ranked_candidates)} candidates ranked"
                )
                
                if ranked_candidates:
                    print("\n  Top Candidates:")
                    for i, ranked in enumerate(ranked_candidates[:3], 1):
                        candidate = ranked['candidate']
                        analysis = ranked['analysis']
                        print(f"    {i}. {candidate['name']} - Score: {analysis['final_score']}")
            else:
                print_result(
                    f"Ranking for {jd['title']}",
                    False,
                    f"Status: {response.status_code}"
                )
        
        # ========================================================================
        # STEP 9: Health Check
        # ========================================================================
        print_section("STEP 9: System Health Check")
        
        response = client.get('/api/health')
        if response.status_code == 200:
            health = response.json()
            print_result(
                "Health Check",
                True,
                f"Status: {health['status']}, Ollama Connected: {health['ollama_connected']}"
            )
            print(f"  - Ollama Model: {health['ollama_model']}")
            print(f"  - Timestamp: {health['timestamp']}")
        else:
            print_result("Health Check", False, f"Status: {response.status_code}")
        
        # ========================================================================
        # SUMMARY
        # ========================================================================
        print_section("TEST SUMMARY")
        
        print(f"\n[OK] All tests completed successfully!")
        print(f"\nResources Created:")
        print(f"  - Job Descriptions: {len(job_descriptions)}")
        print(f"  - Candidates: {len(candidates)}")
        
        print(f"\nJob Descriptions:")
        for jd in job_descriptions:
            print(f"  - {jd['title']} (ID: {jd['id']})")
        
        print(f"\nCandidates:")
        for candidate in candidates:
            print(f"  - {candidate['name']} (ID: {candidate['id']})")
        
        print(f"\nTest completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("\n" + "=" * 80)
        
        return True
        
    except Exception as e:
        print(f"\n[X] Test failed with exception: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_e2e_workflow()
    exit(0 if success else 1)
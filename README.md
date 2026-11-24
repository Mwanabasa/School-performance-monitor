# SPMEWS — Student Performance Monitoring & Early Warning System

AI-assisted monitoring for **Bethel Parents SS**. Teachers enter test, attendance, assignment, project, midterm, and end-of-term records; the system tracks progress, detects declines, estimates failure risk, raises alerts, and suggests interventions. Risk scores inform decisions — they never auto-label a student as a failure.

## Stack

| Layer | Choice |
| --- | --- |
| Framework | Django + Django REST Framework |
| AI / ML | Scikit-Learn |
| Database | PostgreSQL (SQLite for local demo) |
| Data analysis | Pandas |
| Visualisation | Chart.js (dashboard) + Plotly available |

## Features

1. **Monitor performance** — dated assessments and per-student timelines  
2. **Detect decline** — trend slope across assessments  
3. **Predict failure risk** — supervised classification with probability  
4. **Generate alerts** — high risk, decline, attendance, threshold  
5. **Recommend interventions** — remedial lessons, extra work, attendance follow-up, consultations, guardian meetings  

## Quick start (Windows)

```powershell
cd "c:\Users\hanes\OneDrive\Desktop\Perfomance monitor"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py seed_demo
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000/ for the teacher dashboard, or http://127.0.0.1:8000/admin/ for data entry.

## PostgreSQL

1. Create a database named `spmews`.  
2. In `.env` set:

```
DB_ENGINE=postgresql
DB_NAME=spmews
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
```

3. Run `python manage.py migrate` again.

## API highlights

| Method | Path | Purpose |
| --- | --- | --- |
| GET/POST | `/api/students/` | List / create students |
| POST | `/api/students/import_excel/` | Upload Excel/CSV (`file`) |
| GET/POST | `/api/assessments/` | Assessments (always include `date`) |
| GET | `/api/analytics/summary/` | Dashboard counters |
| GET | `/api/analytics/risk-report/` | Learner risk table |
| POST | `/api/analytics/train/` | Train Scikit-Learn model |
| POST | `/api/analytics/predict/` | Batch score all students (`retrain` optional) |
| GET | `/api/analytics/charts/` | Chart.js / Plotly payloads |

## Excel / CSV import

Required columns: `student_id`, `first_name`, `last_name`  

Optional: `classroom`, `gender`, `guardian_name`, `guardian_phone`, `attendance_rate`, score columns such as `test_1`, `assignment_1`, `project_1`, `midterm`, `endterm`  

Sample file: `data/sample_students.csv`

## Project layout

```
config/          Django settings & URLs
students/        Models, REST API, Excel import
analytics/       Pandas features, Scikit-Learn engine, alerts
dashboard/       Teacher UI
templates/       HTML dashboards
static/css/      Dashboard styles
ml_models/       Saved .joblib model
data/            Sample spreadsheets
```

## Notes

- Pass mark defaults to **40%** (`PASS_MARK` in `.env`).  
- Medium / high risk thresholds default to **35%** and **65%** failure probability.  
- Every assessment stores a **date** so trends, not only averages, drive analysis.

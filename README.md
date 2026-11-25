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
2. **Detect decline** — alerts after three consecutive assessment declines
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

Open http://127.0.0.1:8000/ and sign in. The initial superuser is the School Administrator and is redirected to the school dashboard, where they can manage students, promote students, create teacher accounts, assign classrooms/subjects, monitor teacher activity, review class rankings, and plan interventions for high-risk learners. Teachers are redirected to their teaching dashboard, which lists their class/subject assignments and supports class-scoped reports. Teachers can access only assigned students and subjects. Student promotions preserve a dated class-to-class history. The `/admin/` URL is Django's administration site; school administrators have read-only access to assessment and attendance records.

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
| GET/POST | `/api/assessments/` | Subject-scoped assessments; teachers include `subject` and `date` |
| GET/POST | `/api/attendance/` | Dated daily attendance records |
| GET/POST | `/api/attendance-snapshots/` | Dated attendance-rate summaries |
| GET | `/api/analytics/summary/` | Dashboard counters |
| GET | `/api/analytics/risk-report/` | Learner risk table |
| POST | `/api/analytics/train/` | Train Scikit-Learn model |
| POST | `/api/analytics/predict/` | Batch score all students (`retrain` optional) |
| GET | `/api/analytics/charts/` | Chart.js / Plotly payloads |

## Excel / CSV import

Required columns: `student_id`, `first_name`, `last_name`  

Optional: `classroom`, `subject`, `academic_year`, `term`, `gender`, `guardian_name`, `guardian_phone`, `attendance_rate`, and score columns such as `quiz_1`, `test_1`, `assignment_1`, `project_1`, `midterm`, and `endterm`. When score columns are included, teachers must include `subject` unless they have only one subject assignment for that classroom.

Assessment chronology can be provided with `assessment_date` or per-score date columns such as `test_1_date`.

Sample file: `data/sample_students.csv`

Teachers can also add one student at a time from the dashboard's **Add student / import Excel or CSV** page. Student ID and names are required; classroom, gender, date of birth, guardian details, attendance rate, and initial assessment scores are optional. Additional dated assessments can be entered from each student's detail page. Each new assessment is saved in the database and refreshes the student's risk prediction, alerts, and suggested interventions. Attendance-rate values are stored as dated snapshots; actual daily attendance statuses remain separate records. Run `python manage.py migrate` after pulling changes to create the attendance, teacher assignment/activity, promotion, and subject/term assessment fields.

Students with no assessment scores remain unassessed for failure risk rather than receiving a score based only on missing marks. Attendance warnings and follow-up recommendations can still be generated from recorded attendance.

End-of-term results remain part of the student's assessment history and are included as prior-term evidence when estimating risk for later outcomes. Historical model training builds each end-of-term example from assessments recorded before that result to avoid using the result itself as a prediction input. Entering an end-of-term result retrains the model and refreshes cohort predictions, falling back to the existing heuristic when historical data is too sparse.

The dashboards' **Download Excel report** actions export risk analysis, attendance history, term/classroom summaries, pass/fail outcomes, assessment history, alerts, interventions, and overview charts in an `.xlsx` workbook. Teachers can download reports for each assigned class. **Print visual report** opens the browser's print flow, where the teacher dashboard charts can be printed or saved as PDF.

## Project layout

```
config/          Django settings & URLs
students/        Models, REST API, Excel import
analytics/       Pandas features, Scikit-Learn engine, alerts
dashboard/       Teacher and school administrator workflows
templates/       HTML dashboards
static/css/      Dashboard styles
ml_models/       Saved .joblib model
data/            Sample spreadsheets
```

## Notes

- Pass mark defaults to **40%** (`PASS_MARK` in `.env`).  
- Low / medium / high risk bands default to **0–30%**, **31–60%**, and **61–100%** failure probability.
- Attendance alerts and follow-up recommendations trigger below **65%**.
- Every assessment stores a **date** so trends, not only averages, drive analysis.

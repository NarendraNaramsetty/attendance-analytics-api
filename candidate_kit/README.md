# Employee Attendance & Analytics API

A production-ready FastAPI application for managing employee attendance and generating analytics reports.

## Features

- Employee management (create, list, filter by department)
- Attendance tracking (punch-in, punch-out, regularization)
- Real-time analytics (monthly summaries, department insights)
- MongoDB aggregation pipelines for efficient analytics
- Comprehensive indexing strategy for performance at scale
- Concurrent-safe operations with unique constraints
- Full audit trail for manual corrections

## Tech Stack

- **Python 3.11+**
- **FastAPI** - Modern async web framework
- **MongoDB 6.0+** - Document database
- **PyMongo** - MongoDB driver
- **Pydantic** - Data validation
- **Uvicorn** - ASGI server

## Quick Start

### 1. Prerequisites

- Python 3.11 or newer
- MongoDB 6.0 or newer (local installation, Docker, or MongoDB Atlas)

### 2. Set Up MongoDB

**Option A: MongoDB Atlas (Free Cloud)**
1. Sign up at https://www.mongodb.com/cloud/atlas
2. Create a free M0 cluster
3. Get your connection string (looks like `mongodb+srv://username:password@cluster.mongodb.net/`)

**Option B: Local MongoDB**
1. Download from https://www.mongodb.com/try/download/community
2. Install and start the service
3. Default connection: `mongodb://localhost:27017`

**Option C: Docker**
```bash
docker run -d -p 27017:27017 --name mongodb mongo:7
```

### 3. Install Dependencies

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Windows CMD:
.venv\Scripts\activate.bat
# Linux/Mac:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Configure Environment

Create a `.env` file in the project root:

```env
# MongoDB connection string
MONGO_URI=mongodb://localhost:27017
# Or for Atlas:
# MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/

# Database name
MONGO_DB=attendance_db
```

**Important:** Never commit the `.env` file. It's already in `.gitignore`.

### 5. Load Sample Data (Optional)

```bash
python sample_seed.py
```

This loads 6 employees and 9 attendance records for testing.

### 6. Run the Application

```bash
uvicorn app.main:app --port 8000
```

The API will be available at:
- **Interactive Docs:** http://localhost:8000/docs
- **API:** http://localhost:8000
- **Health Check:** http://localhost:8000/health

On startup, you should see:
```
✓ Indexes created successfully
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

## API Documentation

### Interactive Documentation

Visit http://localhost:8000/docs for the full interactive API documentation (Swagger UI).

### Key Endpoints

**Employees:**
- `POST /employees` - Create employee
- `GET /employees` - List employees (with pagination, department filter)

**Attendance:**
- `POST /attendance/punch-in` - Record punch-in
- `POST /attendance/punch-out` - Record punch-out
- `GET /attendance` - List attendance records (with filters, pagination)
- `PATCH /attendance/{emp_code}/{date}` - Regularize (manually correct) a record

**Analytics:**
- `GET /analytics/employees/{emp_code}/monthly` - Monthly summary for one employee
- `GET /analytics/departments/summary` - Department-level summary (not yet implemented)
- `GET /analytics/leaderboard/late` - Late-comers leaderboard (not yet implemented)
- `GET /analytics/departments/{department}/trend` - Daily attendance trend (not yet implemented)

**Admin:**
- `GET /admin/explain/{endpoint}` - MongoDB explain output for query optimization

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MONGO_URI` | Yes | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGO_DB` | Yes | `attendance_db` | Database name |

**Note:** Environment variables take precedence over `.env` file values.

## Development

### Running Tests

```bash
# Load sample data first
python sample_seed.py

# Run business rule tests
python test_business_rules.py

# Generate test data (100k+ records)
python generate_test_data.py

# Verify index usage
python check_indexes.py
```

### Code Structure

```
candidate_kit/
├── app/
│   ├── __init__.py
│   └── main.py              # All application code (single file)
├── sample_data/             # Sample JSON data
│   ├── employees.json
│   └── attendance_logs.json
├── .env                     # Environment config (not in repo)
├── .gitignore
├── requirements.txt
├── sample_seed.py          # Load sample data
├── generate_test_data.py   # Generate 100k+ test records
├── check_indexes.py        # Verify index usage
└── README.md
```

## Performance

### Indexes

The application automatically creates 8 indexes on startup:

**Employees:**
1. `emp_code` (unique) - Primary identifier
2. `department` - Department filtering
3. `(department, joined_on)` - Analytics queries

**Attendance Logs:**
4. `(emp_code, date)` (unique) - Prevents duplicate punch-ins
5. `(date DESC, emp_code ASC)` - List queries with sorting
6. `status` - Status filtering
7. `(date, status)` - Combined filters

### Scalability

Tested with 100,000+ records:
- All queries use indexes (IXSCAN, no COLLSCAN)
- Pagination prevents memory issues
- Aggregation pipelines process data on the database server
- Sub-second response times for analytics endpoints

## Business Rules

The application implements 10 core business rules (R1-R10):

- **R1:** IST timezone handling, overnight shift support
- **R2:** Late calculation with 10-minute grace period
- **R3:** Overtime counted only if >= 30 minutes
- **R4:** Work hours calculated and rounded properly
- **R5:** Half-day detection (< 4.5 hours)
- **R6:** Presence status definitions
- **R7:** Working days (Mon-Fri, counted from joined_on)
- **R8:** Half-up rounding (not banker's rounding)
- **R9:** Headcount includes employees with zero logs
- **R10:** Pagination with stable sorting

See `openapi.yaml` for complete specification.

## Deployment

### Production Checklist

- [ ] Set strong MongoDB credentials
- [ ] Use environment variables (not `.env` file)
- [ ] Enable MongoDB authentication
- [ ] Whitelist specific IPs (not 0.0.0.0/0)
- [ ] Use MongoDB connection pooling
- [ ] Set up monitoring (logs, metrics)
- [ ] Configure HTTPS/TLS
- [ ] Set up backup strategy

### Example Production Deployment

```bash
# Set environment variables
export MONGO_URI="mongodb+srv://prod_user:strong_password@cluster.mongodb.net/"
export MONGO_DB="attendance_prod"

# Run with production server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## Troubleshooting

### MongoDB Connection Failed

```
pymongo.errors.ServerSelectionTimeoutError
```

**Solution:** Check MongoDB is running and `MONGO_URI` is correct.

### Indexes Not Created

Check startup logs for "✓ Indexes created successfully". If missing, verify MongoDB permissions.

### 500 Errors

Check application logs. All business logic errors should return 4xx codes (404, 409, 422), not 500.

### Slow Queries

Use `/admin/explain/{endpoint}` to verify indexes are being used. Look for IXSCAN (good), not COLLSCAN (bad).

## License

This project is part of a hiring assignment and is for evaluation purposes only.

## Contact

For questions or issues, please contact the development team.

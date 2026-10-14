# Project Setup Guide (Windows)

## Prerequisites
- Python 3.11+ installed
- MongoDB 6.0+ (local Docker or Atlas free tier)

## Step 1: Virtual Environment and Dependencies

```powershell
# Navigate to project directory
cd c:\Users\hp\Downloads\SDT_candidate_kit\candidate_kit

# Create virtual environment
python -m venv .venv

# Activate virtual environment
.venv\Scripts\Activate.ps1

# Upgrade pip
python -m pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt
```

## Step 2: MongoDB Setup

### Option A: Local Docker MongoDB (Recommended for Development)

1. Install Docker Desktop for Windows from https://www.docker.com/products/docker-desktop/

2. Run MongoDB in Docker:
```powershell
docker run -d -p 27017:27017 --name mongodb mongo:7
```

3. Your `.env` file should contain:
```
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db
```

### Option B: MongoDB Atlas (Free Cloud Option)

1. Go to https://www.mongodb.com/cloud/atlas/register
2. Create a free account
3. Create a free M0 cluster (takes 3-5 minutes)
4. Click "Connect" → "Drivers"
5. Copy the connection string (looks like `mongodb+srv://username:password@cluster.mongodb.net/`)
6. Create a database user with read/write permissions
7. Whitelist your IP address (or use 0.0.0.0/0 for testing)

8. Your `.env` file should contain:
```
MONGO_URI=mongodb+srv://your_username:your_password@cluster.mongodb.net/
MONGO_DB=attendance_db
```

**Important:** The `.env` file is already in `.gitignore` and will NOT be committed to your repository.

## Step 3: Load Sample Data

The `sample_seed.py` script loads the 9 sample documents into your MongoDB database:
- 6 employee records
- 9 attendance log records

These samples show the document **shapes** only. The actual grading dataset is much larger.

To run the seeder:

```powershell
# Make sure your virtual environment is activated
.venv\Scripts\Activate.ps1

# Run the seeder (reads MONGO_URI and MONGO_DB from .env)
python sample_seed.py
```

Expected output:
```
loaded  6 documents into 'attendance_db.employees'
loaded  9 documents into 'attendance_db.attendance_logs'
```

**What it does:**
1. Connects to MongoDB using MONGO_URI and MONGO_DB from your environment
2. Clears existing data in `employees` and `attendance_logs` collections
3. Loads sample JSON files from `sample_data/` directory
4. Inserts them as MongoDB documents

## Step 4: Start the Application

```powershell
# Make sure your virtual environment is activated
.venv\Scripts\Activate.ps1

# Start the FastAPI server
uvicorn app.main:app --port 8000

# For auto-reload during development (watches for file changes):
uvicorn app.main:app --port 8000 --reload
```

Expected output:
```
INFO:     Started server process [PID]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

## Step 5: Verify the Setup

### Test the Health Endpoint
Open your browser and go to: http://127.0.0.1:8000/health

Expected response:
```json
{"status":"ok"}
```

### Test the Interactive API Documentation
Open your browser and go to: http://127.0.0.1:8000/docs

You should see the FastAPI Swagger UI with all available endpoints.

### Test Creating an Employee

Using the `/docs` interface or with PowerShell:

```powershell
$body = @{
    emp_code = "EMP9999"
    name = "Test Employee"
    email = "test@example.com"
    department = "Engineering"
    joined_on = "2026-10-01"
} | ConvertTo-Json

Invoke-WebRequest -Uri http://127.0.0.1:8000/employees `
    -Method POST `
    -Body $body `
    -ContentType "application/json" `
    -UseBasicParsing
```

## Common Issues

### MongoDB Connection Error
If you get "ServerSelectionTimeoutError":
- **Docker:** Check if MongoDB container is running: `docker ps`
- **Atlas:** Verify your IP is whitelisted and credentials are correct

### Port 8000 Already in Use
Stop the existing process or use a different port:
```powershell
uvicorn app.main:app --port 8001
```

### Module Not Found Errors
Make sure your virtual environment is activated:
```powershell
.venv\Scripts\Activate.ps1
```

## File Structure

```
candidate_kit/
├── app/
│   ├── __init__.py
│   └── main.py          # All application code (single file)
├── sample_data/
│   ├── employees.json
│   └── attendance_logs.json
├── .env                 # MongoDB config (gitignored)
├── .gitignore
├── .venv/               # Virtual environment (gitignored)
├── requirements.txt
├── sample_seed.py       # Loads sample data
├── openapi.yaml         # API contract
├── DATA_MODEL.md        # MongoDB schema
├── PROBLEM_STATEMENT.docx
├── DECISIONS.md
├── REVIEW.md
└── README.md
```

## Next Steps

Now that your environment is set up, you can:
1. Review the starter code defects (see REVIEW.md)
2. Implement the missing endpoints from openapi.yaml
3. Create MongoDB indexes for performance
4. Test with the sample data and your own test cases

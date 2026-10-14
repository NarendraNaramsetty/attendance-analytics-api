"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from decimal import Decimal, ROUND_HALF_UP
import calendar

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pymongo import MongoClient

load_dotenv()

# MongoDB connection with SSL/TLS configuration for Atlas compatibility
import ssl
client = MongoClient(
    os.getenv("MONGO_URI", "mongodb://localhost:27017"),
    tls=True,
    tlsAllowInvalidCertificates=True,  # For development/testing only
    serverSelectionTimeoutMS=5000
)
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


@app.on_event("startup")
def create_indexes():
    """
    Create all required indexes at startup, idempotently.
    MongoDB createIndex is idempotent - if index exists, it's a no-op.
    """
    # EMPLOYEES COLLECTION
    # --------------------
    # 1. Unique index on emp_code (prevents duplicate employees, enforces uniqueness)
    #    Used by: POST /employees (conflict detection), all lookups by emp_code
    db.employees.create_index("emp_code", unique=True, name="idx_emp_code_unique")
    
    # 2. Index on department for filtering
    #    Used by: GET /employees?department=X, department analytics
    db.employees.create_index("department", name="idx_department")
    
    # 3. Index on (department, joined_on) for analytics that filter by dept and need joined_on
    #    Used by: Department summary, department trend (need to count headcount)
    db.employees.create_index([("department", 1), ("joined_on", 1)], name="idx_dept_joined")
    
    # ATTENDANCE_LOGS COLLECTION
    # --------------------------
    # 4. Unique compound index on (emp_code, date) - prevents duplicate punch-ins
    #    Used by: POST /attendance/punch-in (race condition prevention)
    #    Also used by: PATCH /attendance/{emp_code}/{date} (lookup)
    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True,
        name="idx_emp_date_unique"
    )
    
    # 5. Index on (date, emp_code) for date range queries with sorting
    #    Used by: GET /attendance (sorted by date DESC, emp_code ASC)
    #    Note: Order matters! date is filtered and sorted first, then emp_code for ties
    db.attendance_logs.create_index(
        [("date", -1), ("emp_code", 1)],
        name="idx_date_emp"
    )
    
    # 6. Index on (emp_code, date) for employee-specific queries
    #    Used by: GET /analytics/employees/{emp_code}/monthly (filter by emp_code, date range)
    #    Note: This is redundant with index #4 but MongoDB can use it for non-unique queries
    #    Actually, index #4 already covers this pattern
    
    # 7. Index on (status) for status filtering
    #    Used by: GET /attendance?status=X
    db.attendance_logs.create_index("status", name="idx_status")
    
    # 8. Index on (date, status) for date+status combined filters
    #    Used by: Analytics that filter by month and need to identify LEAVE/ABSENT records
    db.attendance_logs.create_index([("date", 1), ("status", 1)], name="idx_date_status")
    
    print("✓ Indexes created successfully")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    h, m = map(int, shift_start.split(":"))
    start = punch_in.replace(hour=h, minute=m, second=0, microsecond=0)
    minutes = int((punch_in - start).total_seconds() / 60)
    return minutes if minutes > 10 else 0


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    return round((punch_out - punch_in).total_seconds() / 3600, 2)


def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:
    h, m = map(int, shift_end.split(":"))
    end = datetime.fromisoformat(date_str).replace(hour=h, minute=m, tzinfo=IST)
    return max(0, int((punch_out - end).total_seconds() / 60))


def recompute_derived_fields(record: dict, employee: dict) -> dict:
    """
    Recompute work_hours, late_minutes, overtime_minutes, and half_day
    from the current punch times and employee shift.
    Returns a dict with the updated derived fields.
    """
    result = {
        "work_hours": None,
        "late_minutes": 0,
        "overtime_minutes": 0,
        "half_day": False,
    }
    
    # For ABSENT/LEAVE, all derived fields are 0/False/None
    if record.get("status") in ("ABSENT", "LEAVE"):
        return result
    
    # Need punch_in for presence statuses
    punch_in = record.get("punch_in")
    if not punch_in:
        return result
    
    # Compute late_minutes from punch_in
    result["late_minutes"] = compute_late_minutes(punch_in, employee["shift_start"])
    
    # If we have punch_out, compute work_hours, overtime, and half_day
    punch_out = record.get("punch_out")
    if punch_out:
        result["work_hours"] = compute_work_hours(punch_in, punch_out)
        result["overtime_minutes"] = compute_overtime(
            punch_out, employee["shift_end"], record["date"]
        )
        # Half day: rounded work_hours < 4.50
        if result["work_hours"] is not None and result["work_hours"] < 4.50:
            result["half_day"] = True
    
    return result


def count_working_days(year: int, month: int, joined_on: str) -> int:
    """
    Count Mon-Fri working days in a month, starting from joined_on if mid-month.
    R7: Mon-Fri, no holiday calendar.
    """
    # Get first and last day of the month
    first_day = datetime(year, month, 1).date()
    last_day = datetime(year, month, calendar.monthrange(year, month)[1]).date()
    
    # If employee joined mid-month, start from joined_on
    joined_date = datetime.fromisoformat(joined_on).date()
    start_date = max(first_day, joined_date)
    
    # If joined after the month, no working days
    if start_date > last_day:
        return 0
    
    # Count Mon-Fri days
    working_days = 0
    current = start_date
    while current <= last_day:
        # Monday = 0, Sunday = 6
        if current.weekday() < 5:
            working_days += 1
        current += timedelta(days=1)
    
    return working_days


def round_half_up(value: float, decimals: int) -> float:
    """
    Round using half-up rounding (0.5 always rounds up), not banker's rounding.
    R8: 2 decimals half-up for most numbers, 4 decimals for rates.
    """
    if value is None:
        return None
    d = Decimal(str(value))
    quantize_str = "0." + "0" * decimals
    return float(d.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP))


def build_employee_monthly_pipeline(emp_code: str, month: str) -> list:
    """
    Build MongoDB aggregation pipeline for employee monthly analytics.
    
    Returns: [pipeline_stages], year, month_num for use in working_days calculation.
    
    The pipeline:
    1. Matches all attendance records for the employee in the given month
    2. Adds computed fields (day of week, is_weekday, present_value accounting for half_day)
    3. Groups to calculate totals
    4. Projects final response shape
    """
    # Parse month string "YYYY-MM"
    year, month_num = map(int, month.split("-"))
    
    # First and last day of the month as strings
    first_day = f"{year}-{month_num:02d}-01"
    last_day = f"{year}-{month_num:02d}-{calendar.monthrange(year, month_num)[1]:02d}"
    
    pipeline = [
        # Stage 1: Match records for this employee and month
        {
            "$match": {
                "emp_code": emp_code,
                "date": {"$gte": first_day, "$lte": last_day}
            }
        },
        
        # Stage 2: Add computed fields for each record
        {
            "$addFields": {
                # Convert date string to date object to get day of week
                "date_obj": {"$dateFromString": {"dateString": "$date"}},
                
                # Compute present_value: 1.0 for full day, 0.5 for half day, 0 for non-presence
                "present_value": {
                    "$cond": {
                        "if": {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                        "then": {
                            "$cond": {
                                "if": {"$ifNull": ["$half_day", False]},
                                "then": 0.5,
                                "else": 1.0
                            }
                        },
                        "else": 0.0
                    }
                }
            }
        },
        
        # Stage 3: Add day of week field
        {
            "$addFields": {
                # dayOfWeek: 1=Sunday, 2=Monday, ..., 7=Saturday
                "day_of_week": {"$dayOfWeek": "$date_obj"},
                
                # is_weekday: true for Mon-Fri (dayOfWeek 2-6)
                "is_weekday": {
                    "$and": [
                        {"$gte": [{"$dayOfWeek": "$date_obj"}, 2]},
                        {"$lte": [{"$dayOfWeek": "$date_obj"}, 6]}
                    ]
                }
            }
        },
        
        # Stage 4: Group all records to compute totals
        {
            "$group": {
                "_id": None,
                
                # present_days: sum of present_value for weekday records only (R7)
                "present_days": {
                    "$sum": {
                        "$cond": {
                            "if": "$is_weekday",
                            "then": "$present_value",
                            "else": 0
                        }
                    }
                },
                
                # leave_days: count of LEAVE records (any day)
                "leave_days": {
                    "$sum": {
                        "$cond": {
                            "if": {"$eq": ["$status", "LEAVE"]},
                            "then": 1,
                            "else": 0
                        }
                    }
                },
                
                # late_count: count records with late_minutes > 0 (any day, R7 note)
                "late_count": {
                    "$sum": {
                        "$cond": {
                            "if": {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]},
                            "then": 1,
                            "else": 0
                        }
                    }
                },
                
                # total_late_minutes: sum late_minutes (any day)
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },
                
                # total_overtime_minutes: sum overtime_minutes (any day)
                "total_overtime_minutes": {
                    "$sum": {"$ifNull": ["$overtime_minutes", 0]}
                }
            }
        },
        
        # Stage 5: Project final shape (working_days added in Python)
        {
            "$project": {
                "_id": 0,
                "present_days": 1,
                "leave_days": 1,
                "late_count": 1,
                "total_late_minutes": 1,
                "total_overtime_minutes": 1
            }
        }
    ]
    
    return pipeline, year, month_num


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"


class RegularizeRequest(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    reason: str
    regularized_by: str


# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")
    doc = body.model_dump()
    doc["created_at"] = datetime.now()
    db.employees.insert_one(doc)
    doc.pop("_id", None)
    return doc


@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = 1, page_size: int = 20):
    q = {}
    if department:
        q["department"] = department
    skip = page * page_size
    total = db.employees.count_documents({})
    items = list(db.employees.find(q, {"_id": 0}).skip(skip).limit(page_size))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    ts = datetime.fromtimestamp(body.punched_at / 1000) if body.punched_at else datetime.now()
    d = ts.date().isoformat()
    if db.attendance_logs.find_one({"emp_code": body.emp_code, "date": d}):
        raise HTTPException(409, "already punched in for this date")
    doc = {
        "emp_code": body.emp_code,
        "date": d,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, emp["shift_start"]),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    res = db.attendance_logs.insert_one(doc)
    doc["id"] = str(res.inserted_id)
    doc.pop("_id", None)
    return doc


def build_attendance_list_query(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20
):
    """
    Build the query, sort, skip, and limit for GET /attendance.
    Returns: (query_filter, sort_spec, skip, limit)
    """
    # Validate date range
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must be <= date_to")
    
    # Build filter
    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status
    
    # Sort: date DESC, emp_code ASC (for stable pagination)
    sort_spec = [("date", -1), ("emp_code", 1)]
    
    # Pagination
    skip = (page - 1) * page_size
    limit = page_size
    
    return q, sort_spec, skip, limit


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    q, sort_spec, skip, limit = build_attendance_list_query(
        emp_code, date_from, date_to, status, page, page_size
    )
    
    # Count total matching documents
    total = db.attendance_logs.count_documents(q)
    
    # Fetch paginated results with proper sorting
    cursor = db.attendance_logs.find(q, {"_id": 0}).sort(sort_spec).skip(skip).limit(limit)
    items = []
    
    for doc in cursor:
        # Convert datetime fields to epoch milliseconds
        if doc.get("punch_in"):
            doc["punch_in"] = int(doc["punch_in"].timestamp() * 1000)
        if doc.get("punch_out"):
            doc["punch_out"] = int(doc["punch_out"].timestamp() * 1000)
        
        # Convert history timestamps
        for entry in doc.get("history", []):
            if entry.get("at"):
                entry["at"] = int(entry["at"].timestamp() * 1000)
        
        # Ensure defaults for missing fields
        if "half_day" not in doc:
            doc["half_day"] = False
        if "history" not in doc:
            doc["history"] = []
        
        items.append(doc)
    
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(emp_code: str, date: str, body: RegularizeRequest):
    """
    Regularize (manually correct) an attendance record.
    
    Validates rules, recomputes derived fields, appends history atomically.
    Concurrent corrections are safe - each appends its own history entry.
    """
    # 1. Find the employee
    emp = db.employees.find_one({"emp_code": emp_code}, {"_id": 0})
    if not emp:
        raise HTTPException(404, "employee not found")
    
    # 2. Find the attendance record
    old_record = db.attendance_logs.find_one({"emp_code": emp_code, "date": date})
    if not old_record:
        raise HTTPException(404, "attendance record not found")
    
    # 3. Build the update based on what fields are provided
    updates = {}
    
    # Status changes
    new_status = body.status if body.status is not None else old_record.get("status")
    if body.status is not None:
        updates["status"] = body.status
    
    # Punch time changes
    new_punch_in = old_record.get("punch_in")
    new_punch_out = old_record.get("punch_out")
    
    if body.punch_in is not None:
        # Convert epoch ms to datetime
        new_punch_in = datetime.fromtimestamp(body.punch_in / 1000, tz=timezone.utc)
        updates["punch_in"] = new_punch_in
    
    if body.punch_out is not None:
        # Convert epoch ms to datetime
        new_punch_out = datetime.fromtimestamp(body.punch_out / 1000, tz=timezone.utc)
        updates["punch_out"] = new_punch_out
    
    # 4. Validate status-based rules
    # ABSENT/LEAVE require both punch times null
    if new_status in ("ABSENT", "LEAVE"):
        if body.punch_in is not None or body.punch_out is not None:
            raise HTTPException(
                422,
                "ABSENT and LEAVE statuses require both punch times to be null"
            )
        # Clear punch times
        updates["punch_in"] = None
        updates["punch_out"] = None
        new_punch_in = None
        new_punch_out = None
    
    # Presence statuses require punch_in
    if new_status in ("PRESENT", "WFH", "ON_DUTY"):
        if new_punch_in is None:
            raise HTTPException(
                422,
                f"{new_status} status requires punch_in"
            )
    
    # 5. Validate punch_out > punch_in and within 24 hours
    if new_punch_in and new_punch_out:
        if new_punch_out <= new_punch_in:
            raise HTTPException(422, "punch_out must be after punch_in")
        
        delta = (new_punch_out - new_punch_in).total_seconds()
        if delta > 86400:  # 24 hours
            raise HTTPException(422, "punch_out must be within 24 hours of punch_in")
    
    # 6. Check if anything actually changed
    if not updates:
        raise HTTPException(422, "no changes specified")
    
    # Also check if the values are actually different from current
    changes_made = {}
    for field, new_value in updates.items():
        old_value = old_record.get(field)
        if old_value != new_value:
            changes_made[field] = {"from": old_value, "to": new_value}
    
    if not changes_made:
        raise HTTPException(422, "no actual changes - all fields already have the specified values")
    
    # 7. Recompute derived fields
    # Build a temp record with the new values for recomputation
    temp_record = {
        "date": date,
        "status": new_status,
        "punch_in": new_punch_in,
        "punch_out": new_punch_out,
    }
    
    derived = recompute_derived_fields(temp_record, emp)
    
    # Track derived field changes
    for field in ["work_hours", "late_minutes", "overtime_minutes", "half_day"]:
        old_value = old_record.get(field, 0 if field != "work_hours" else None)
        if field == "half_day":
            old_value = old_record.get(field, False)
        new_value = derived[field]
        
        if old_value != new_value:
            changes_made[field] = {"from": old_value, "to": new_value}
        
        updates[field] = new_value
    
    # 8. Build the history entry
    # Convert datetime values to epoch milliseconds for history
    history_changes = {}
    for field, change in changes_made.items():
        from_val = change["from"]
        to_val = change["to"]
        
        # Convert datetimes to epoch ms for history
        if isinstance(from_val, datetime):
            from_val = int(from_val.timestamp() * 1000)
        if isinstance(to_val, datetime):
            to_val = int(to_val.timestamp() * 1000)
        
        history_changes[field] = {"from": from_val, "to": to_val}
    
    history_entry = {
        "at": datetime.now(timezone.utc),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": history_changes,
    }
    
    # 9. Atomic update: set fields and push history entry
    # This ensures concurrent updates each append their own history
    result = db.attendance_logs.update_one(
        {"emp_code": emp_code, "date": date},
        {
            "$set": updates,
            "$push": {"history": history_entry}
        }
    )
    
    if result.matched_count == 0:
        raise HTTPException(404, "attendance record not found")
    
    # 10. Fetch and return the updated record
    updated = db.attendance_logs.find_one({"emp_code": emp_code, "date": date}, {"_id": 0})
    
    # Convert datetime fields to epoch milliseconds for response
    if updated.get("punch_in"):
        updated["punch_in"] = int(updated["punch_in"].timestamp() * 1000)
    if updated.get("punch_out"):
        updated["punch_out"] = int(updated["punch_out"].timestamp() * 1000)
    
    # Convert history timestamps
    for entry in updated.get("history", []):
        if entry.get("at"):
            entry["at"] = int(entry["at"].timestamp() * 1000)
    
    # Ensure missing fields are present with defaults
    if "half_day" not in updated:
        updated["half_day"] = False
    if "history" not in updated:
        updated["history"] = []
    
    return updated


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str):
    """
    Monthly attendance summary for one employee.
    
    Uses MongoDB aggregation to compute totals from stored derived fields.
    Working days calculated in Python per R7 (Mon-Fri from joined_on).
    """
    # 1. Find the employee
    emp = db.employees.find_one({"emp_code": emp_code}, {"_id": 0, "joined_on": 1})
    if not emp:
        raise HTTPException(404, "employee not found")
    
    # 2. Build and run aggregation pipeline
    pipeline, year, month_num = build_employee_monthly_pipeline(emp_code, month)
    result = list(db.attendance_logs.aggregate(pipeline))
    
    # 3. Get aggregation results or defaults if no records
    if result:
        data = result[0]
    else:
        data = {
            "present_days": 0,
            "leave_days": 0,
            "late_count": 0,
            "total_late_minutes": 0,
            "total_overtime_minutes": 0
        }
    
    # 4. Calculate working_days from employee's joined_on
    working_days = count_working_days(year, month_num, emp["joined_on"])
    
    # 5. Calculate attendance percentage (R8: 2 decimals half-up)
    if working_days > 0:
        attendance_pct = (data["present_days"] / working_days) * 100
        attendance_pct = round_half_up(attendance_pct, 2)
    else:
        attendance_pct = None
    
    # 6. Round present_days to 2 decimals (can be 0.5 for half days)
    present_days = round_half_up(data["present_days"], 2)
    
    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": data["leave_days"],
        "late_count": data["late_count"],
        "total_late_minutes": data["total_late_minutes"],
        "total_overtime_minutes": data["total_overtime_minutes"],
        "attendance_pct": attendance_pct
    }


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    # Common params
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    limit: int = 10,
    # attendance_list params
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    # department_trend params
    from_date: Optional[str] = None,  # renamed to avoid conflict
    to_date: Optional[str] = None,
):
    """
    Returns MongoDB explain output for the main query/aggregation of an endpoint.
    
    Runs explain with executionStats verbosity on the SAME query built by the real endpoint.
    Use this to verify indexes are being used (look for IXSCAN, no COLLSCAN).
    """
    
    if endpoint == "attendance_list":
        # GET /attendance
        q, sort_spec, skip, limit_val = build_attendance_list_query(
            emp_code, date_from, date_to, status, page, page_size
        )
        
        # Build explain for find query with sort, skip, limit
        explain_result = db.attendance_logs.find(q).sort(sort_spec).skip(skip).limit(limit_val).explain()
        
        return {
            "endpoint": "attendance_list",
            "collection": "attendance_logs",
            "explain": explain_result
        }
    
    elif endpoint == "employee_monthly":
        # GET /analytics/employees/{emp_code}/monthly
        if not emp_code or not month:
            raise HTTPException(422, "emp_code and month are required for employee_monthly")
        
        # Check employee exists (same as real endpoint)
        emp = db.employees.find_one({"emp_code": emp_code}, {"_id": 0, "joined_on": 1})
        if not emp:
            raise HTTPException(404, "employee not found")
        
        # Build the same pipeline the real endpoint uses
        pipeline, year, month_num = build_employee_monthly_pipeline(emp_code, month)
        
        # Run explain on the aggregation
        explain_result = db.attendance_logs.aggregate(pipeline, explain=True)
        # For aggregations, explain=True returns the explain output directly
        # But we need to consume the cursor to get the stages
        explain_doc = db.command('aggregate', 'attendance_logs', pipeline=pipeline, explain=True)
        
        return {
            "endpoint": "employee_monthly",
            "collection": "attendance_logs",
            "explain": explain_doc
        }
    
    elif endpoint == "department_summary":
        # GET /analytics/departments/summary (not implemented yet)
        raise HTTPException(501, "department_summary endpoint not implemented yet")
    
    elif endpoint == "late_leaderboard":
        # GET /analytics/leaderboard/late (not implemented yet)
        raise HTTPException(501, "late_leaderboard endpoint not implemented yet")
    
    elif endpoint == "department_trend":
        # GET /analytics/departments/{department}/trend (not implemented yet)
        raise HTTPException(501, "department_trend endpoint not implemented yet")
    
    else:
        raise HTTPException(404, f"unknown endpoint: {endpoint}")


# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #

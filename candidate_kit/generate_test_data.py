"""
Generate 100,000 attendance records for testing index performance.

Creates:
- 200 employees across 5 departments
- ~500 attendance records per employee over 10 months
- Mix of statuses, late records, overtime, half days, weekend records

Run: python generate_test_data.py
"""
import os
import random
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), tz_aware=True)
db = client[os.getenv("MONGO_DB", "attendance_db")]

# Configuration
NUM_EMPLOYEES = 200
MONTHS_OF_DATA = 10  # Will generate ~100k records
START_DATE = datetime(2026, 1, 1).date()
DEPARTMENTS = ["Engineering", "Sales", "Support", "HR", "Finance"]
SHIFTS = [
    ("09:30", "18:30"),  # Regular day shift
    ("22:00", "06:00"),  # Night shift
]

IST = timezone(timedelta(hours=5, minutes=30))

print("Clearing existing data...")
db.employees.delete_many({})
db.attendance_logs.delete_many({})

print(f"Generating {NUM_EMPLOYEES} employees...")
employees = []
for i in range(1, NUM_EMPLOYEES + 1):
    emp_code = f"TEST{i:04d}"
    dept = random.choice(DEPARTMENTS)
    shift = random.choice(SHIFTS)
    
    # Random join date in the past year
    days_ago = random.randint(30, 365)
    joined_on = (START_DATE - timedelta(days=days_ago)).isoformat()
    
    emp = {
        "emp_code": emp_code,
        "name": f"Test Employee {i}",
        "email": f"test{i}@example.com",
        "department": dept,
        "shift_start": shift[0],
        "shift_end": shift[1],
        "joined_on": joined_on,
        "created_at": datetime.now(timezone.utc)
    }
    employees.append(emp)

db.employees.insert_many(employees)
print(f"✓ Created {NUM_EMPLOYEES} employees")

print(f"Generating attendance records for {MONTHS_OF_DATA} months...")
attendance_records = []
record_count = 0

for emp in employees:
    emp_code = emp["emp_code"]
    shift_start_time = emp["shift_start"]
    shift_end_time = emp["shift_end"]
    joined_date = datetime.fromisoformat(emp["joined_on"]).date()
    
    # Generate records from join date or start date, whichever is later
    current_date = max(joined_date, START_DATE)
    end_date = START_DATE + timedelta(days=MONTHS_OF_DATA * 30)
    
    while current_date < end_date:
        # 80% chance of having a record on weekdays, 10% on weekends
        is_weekday = current_date.weekday() < 5
        if (is_weekday and random.random() < 0.80) or (not is_weekday and random.random() < 0.10):
            
            # Determine status
            rand = random.random()
            if rand < 0.85:
                status = "PRESENT"
            elif rand < 0.92:
                status = "WFH"
            elif rand < 0.95:
                status = "ON_DUTY"
            elif rand < 0.97:
                status = "LEAVE"
            else:
                status = "ABSENT"
            
            if status in ("LEAVE", "ABSENT"):
                # No punch times
                rec = {
                    "emp_code": emp_code,
                    "date": current_date.isoformat(),
                    "status": status,
                    "punch_in": None,
                    "punch_out": None,
                    "work_hours": None,
                    "late_minutes": 0,
                    "overtime_minutes": 0,
                    "half_day": False,
                    "history": []
                }
            else:
                # Generate punch times
                shift_h, shift_m = map(int, shift_start_time.split(":"))
                
                # Punch in: 70% on time, 20% late, 10% early
                rand = random.random()
                if rand < 0.70:
                    # On time (within grace period)
                    late_mins = random.randint(0, 10)
                elif rand < 0.90:
                    # Late
                    late_mins = random.randint(11, 90)
                else:
                    # Early
                    late_mins = random.randint(-30, -1)
                
                punch_in_time = datetime.combine(
                    current_date,
                    datetime.min.time().replace(hour=shift_h, minute=shift_m)
                )
                punch_in_time += timedelta(minutes=late_mins)
                punch_in = punch_in_time.replace(tzinfo=IST)
                
                # Compute late_minutes per R2
                if late_mins > 10:
                    late_minutes = late_mins
                else:
                    late_minutes = 0
                
                # Work hours: 3-11 hours
                work_hours_float = random.uniform(3.0, 11.0)
                
                # Half day if < 4.5 hours
                half_day = work_hours_float < 4.5
                
                punch_out = punch_in + timedelta(hours=work_hours_float)
                
                # Overtime: if work > 9 hours, maybe overtime
                if work_hours_float > 9 and random.random() < 0.5:
                    overtime_minutes = int((work_hours_float - 9) * 60)
                else:
                    overtime_minutes = 0
                
                # Round work hours to 2 decimals
                work_hours = round(work_hours_float, 2)
                
                rec = {
                    "emp_code": emp_code,
                    "date": current_date.isoformat(),
                    "status": status,
                    "punch_in": punch_in,
                    "punch_out": punch_out,
                    "work_hours": work_hours,
                    "late_minutes": late_minutes,
                    "overtime_minutes": overtime_minutes,
                    "half_day": half_day,
                    "history": []
                }
            
            attendance_records.append(rec)
            record_count += 1
            
            # Batch insert every 1000 records
            if len(attendance_records) >= 1000:
                db.attendance_logs.insert_many(attendance_records)
                print(f"  Inserted {record_count} records...", end="\r")
                attendance_records = []
        
        current_date += timedelta(days=1)

# Insert remaining records
if attendance_records:
    db.attendance_logs.insert_many(attendance_records)

print(f"\n✓ Created {record_count} attendance records")

# Verify counts
emp_count = db.employees.count_documents({})
att_count = db.attendance_logs.count_documents({})
print(f"\nFinal counts:")
print(f"  Employees: {emp_count}")
print(f"  Attendance records: {att_count}")
print(f"\n✓ Test data generation complete!")
print(f"\nNow run the app and test:")
print(f"  GET /admin/explain/attendance_list")
print(f"  GET /admin/explain/employee_monthly?emp_code=TEST0001&month=2026-01")

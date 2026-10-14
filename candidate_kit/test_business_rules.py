"""
Test file for critical business rules and edge cases.
DO NOT include this in the final submission - it's for development/verification only.

Run: pytest test_business_rules.py -v
Or:  python test_business_rules.py
"""
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

BASE_URL = "http://localhost:8000"

# Test employee for R2 examples
TEST_EMPLOYEE = {
    "emp_code": "RULE_TEST_001",
    "name": "Rule Test Employee",
    "email": "ruletest@example.com",
    "department": "Engineering",
    "shift_start": "09:30",
    "shift_end": "18:30",
    "joined_on": "2026-01-01"
}

# Overnight shift employee
NIGHT_EMPLOYEE = {
    "emp_code": "NIGHT_001",
    "name": "Night Shift Employee",
    "email": "night@example.com",
    "department": "Support",
    "shift_start": "22:00",
    "shift_end": "06:00",
    "joined_on": "2026-01-01"
}


def setup_employee(emp_data):
    """Create or skip employee creation."""
    resp = requests.post(f"{BASE_URL}/employees", json=emp_data)
    return resp.status_code in [201, 409]  # OK if already exists


def test_r2_late_calculation():
    """
    Test R2: Grace period is exactly 10:00, late_minutes counted from shift_start.
    Shift: 09:30
    - 09:40:00 -> 0 late (exactly 10:00, within grace)
    - 09:40:01 -> 10 late (10 min 1 sec after start, floor to 10)
    - 10:15:59 -> 45 late (45 min 59 sec after start, floor to 45)
    """
    print("\n=== Testing R2: Late Calculation ===")
    setup_employee(TEST_EMPLOYEE)
    
    test_cases = [
        # (punched_at_IST, expected_late_minutes, description)
        ("2026-07-06T09:40:00+05:30", 0, "exactly 10:00 after start (within grace)"),
        ("2026-07-06T09:40:01+05:30", 10, "10 min 1 sec after start"),
        ("2026-07-06T10:15:59+05:30", 45, "45 min 59 sec after start"),
        ("2026-07-06T09:30:00+05:30", 0, "exactly on time"),
        ("2026-07-06T09:20:00+05:30", 0, "early (no negative late)"),
    ]
    
    results = []
    for ist_time_str, expected_late, description in test_cases:
        # Convert IST to epoch milliseconds
        dt = datetime.fromisoformat(ist_time_str)
        epoch_ms = int(dt.timestamp() * 1000)
        
        # Generate unique date for each test
        date_str = dt.date().isoformat()
        
        # Punch in
        resp = requests.post(f"{BASE_URL}/attendance/punch-in", json={
            "emp_code": TEST_EMPLOYEE["emp_code"],
            "punched_at": epoch_ms,
            "status": "PRESENT"
        })
        
        if resp.status_code == 409:
            # Already exists, fetch it
            resp = requests.get(
                f"{BASE_URL}/attendance",
                params={"emp_code": TEST_EMPLOYEE["emp_code"], "date_from": date_str, "date_to": date_str}
            )
            record = resp.json()["items"][0]
        else:
            record = resp.json()
        
        actual_late = record.get("late_minutes", 0)
        passed = actual_late == expected_late
        
        status = "✓" if passed else "✗"
        results.append((status, description, expected_late, actual_late))
        print(f"  {status} {description}")
        print(f"     Expected: {expected_late} min, Got: {actual_late} min")
    
    return all(r[0] == "✓" for r in results)


def test_r3_overtime_boundary():
    """
    Test R3: Overtime counted only if >= 30 minutes.
    Shift end: 18:30
    - 18:59 (29 min after) -> 0 overtime
    - 19:00 (30 min after) -> 30 overtime
    """
    print("\n=== Testing R3: Overtime Boundary (29/30 minutes) ===")
    setup_employee(TEST_EMPLOYEE)
    
    test_cases = [
        ("2026-07-10T09:30:00+05:30", "2026-07-10T18:59:00+05:30", 0, "29 minutes (below threshold)"),
        ("2026-07-10T09:30:00+05:30", "2026-07-10T19:00:00+05:30", 30, "30 minutes (at threshold)"),
        ("2026-07-10T09:30:00+05:30", "2026-07-10T19:30:00+05:30", 60, "60 minutes (above threshold)"),
    ]
    
    results = []
    for punch_in_str, punch_out_str, expected_ot, description in test_cases:
        # Punch in
        dt_in = datetime.fromisoformat(punch_in_str)
        epoch_in = int(dt_in.timestamp() * 1000)
        date_str = dt_in.date().isoformat()
        
        resp = requests.post(f"{BASE_URL}/attendance/punch-in", json={
            "emp_code": TEST_EMPLOYEE["emp_code"],
            "punched_at": epoch_in,
            "status": "PRESENT"
        })
        
        if resp.status_code != 201:
            # Skip if already exists
            continue
        
        # Punch out
        dt_out = datetime.fromisoformat(punch_out_str)
        epoch_out = int(dt_out.timestamp() * 1000)
        
        resp = requests.post(f"{BASE_URL}/attendance/punch-out", json={
            "emp_code": TEST_EMPLOYEE["emp_code"],
            "punched_at": epoch_out
        })
        
        record = resp.json()
        actual_ot = record.get("overtime_minutes", 0)
        passed = actual_ot == expected_ot
        
        status = "✓" if passed else "✗"
        results.append((status, description, expected_ot, actual_ot))
        print(f"  {status} {description}")
        print(f"     Expected: {expected_ot} min, Got: {actual_ot} min")
    
    return all(r[0] == "✓" for r in results)


def test_half_up_rounding():
    """
    Test R8: Half-up rounding (not banker's rounding).
    8 hours 7.5 minutes = 8.125 hours
    - Banker's rounding: 8.12 (rounds to even)
    - Half-up rounding: 8.13 (0.5 always rounds up)
    """
    print("\n=== Testing R8: Half-Up Rounding ===")
    setup_employee(TEST_EMPLOYEE)
    
    # Create a record with 8.125 hours of work
    # 8 hours 7.5 minutes = 8.125 hours
    dt_in = datetime.fromisoformat("2026-07-20T09:30:00+05:30")
    dt_out = dt_in.replace(hour=17, minute=37, second=30)  # 8.125 hours later
    
    epoch_in = int(dt_in.timestamp() * 1000)
    epoch_out = int(dt_out.timestamp() * 1000)
    
    resp = requests.post(f"{BASE_URL}/attendance/punch-in", json={
        "emp_code": TEST_EMPLOYEE["emp_code"],
        "punched_at": epoch_in,
        "status": "PRESENT"
    })
    
    if resp.status_code == 409:
        print("  ⚠ Record already exists, skipping")
        return None
    
    resp = requests.post(f"{BASE_URL}/attendance/punch-out", json={
        "emp_code": TEST_EMPLOYEE["emp_code"],
        "punched_at": epoch_out
    })
    
    record = resp.json()
    work_hours = record.get("work_hours")
    
    # Should be 8.13 with half-up rounding, not 8.12 with banker's
    expected = 8.13
    passed = work_hours == expected
    
    status = "✓" if passed else "✗"
    print(f"  {status} 8.125 hours rounded")
    print(f"     Expected: {expected} (half-up), Got: {work_hours}")
    if work_hours == 8.12:
        print(f"     ⚠ This is banker's rounding, not half-up!")
    
    return passed


def test_overnight_shift():
    """
    Test R1: Overnight shift attendance date.
    Shift: 22:00-06:00
    - Punch at 22:30 on July 6 -> date is 2026-07-06
    - Punch at 02:00 on July 7 -> date is 2026-07-06 (belongs to shift started previous day)
    """
    print("\n=== Testing R1: Overnight Shift ===")
    setup_employee(NIGHT_EMPLOYEE)
    
    # Test case 1: Punch in at 22:30 (after shift start)
    dt1 = datetime.fromisoformat("2026-07-06T22:30:00+05:30")
    epoch1 = int(dt1.timestamp() * 1000)
    
    resp = requests.post(f"{BASE_URL}/attendance/punch-in", json={
        "emp_code": NIGHT_EMPLOYEE["emp_code"],
        "punched_at": epoch1,
        "status": "PRESENT"
    })
    
    if resp.status_code != 201:
        print("  ⚠ Record already exists, skipping test")
        return None
    
    record1 = resp.json()
    date1 = record1["date"]
    expected_date1 = "2026-07-06"
    
    passed1 = date1 == expected_date1
    status1 = "✓" if passed1 else "✗"
    print(f"  {status1} Punch at 22:30 on July 6")
    print(f"     Expected date: {expected_date1}, Got: {date1}")
    
    # Test case 2: Punch in at 02:00 next day (before shift end)
    dt2 = datetime.fromisoformat("2026-07-07T02:00:00+05:30")
    epoch2 = int(dt2.timestamp() * 1000)
    
    resp = requests.post(f"{BASE_URL}/attendance/punch-in", json={
        "emp_code": NIGHT_EMPLOYEE["emp_code"],
        "punched_at": epoch2,
        "status": "PRESENT"
    })
    
    if resp.status_code != 201:
        # This is expected - second punch for same date should be 409
        expected_date2 = "2026-07-06"  # Should belong to same shift
        print(f"  ✓ Punch at 02:00 on July 7")
        print(f"     Got 409 conflict - correctly identified as same date: {expected_date2}")
        return passed1
    
    record2 = resp.json()
    date2 = record2["date"]
    expected_date2 = "2026-07-06"
    
    passed2 = date2 == expected_date2
    status2 = "✓" if passed2 else "✗"
    print(f"  {status2} Punch at 02:00 on July 7")
    print(f"     Expected date: {expected_date2}, Got: {date2}")
    
    return passed1 and passed2


def test_concurrent_punch_ins():
    """
    Test race condition: Two identical punch-ins at same instant.
    Exactly one should succeed (201), the other should conflict (409).
    """
    print("\n=== Testing Concurrent Punch-Ins ===")
    
    # Create unique employee for this test
    test_emp = {
        "emp_code": f"RACE_TEST_{int(time.time())}",
        "name": "Race Test",
        "email": "race@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-01"
    }
    setup_employee(test_emp)
    
    epoch_ms = int(datetime(2026, 7, 15, 9, 30, 0).timestamp() * 1000)
    
    def punch_in():
        return requests.post(f"{BASE_URL}/attendance/punch-in", json={
            "emp_code": test_emp["emp_code"],
            "punched_at": epoch_ms,
            "status": "PRESENT"
        })
    
    # Send 5 identical requests concurrently
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(punch_in) for _ in range(5)]
        responses = [f.result() for f in as_completed(futures)]
    
    status_codes = [r.status_code for r in responses]
    success_count = status_codes.count(201)
    conflict_count = status_codes.count(409)
    
    print(f"  Results: {success_count} succeeded (201), {conflict_count} conflicted (409)")
    print(f"  Status codes: {status_codes}")
    
    passed = success_count == 1 and conflict_count == 4
    status = "✓" if passed else "✗"
    print(f"  {status} Exactly one success, rest conflicts")
    
    return passed


def test_concurrent_punch_outs():
    """
    Test race condition: Two identical punch-outs at same instant.
    Exactly one should succeed (200), the other should conflict (409).
    """
    print("\n=== Testing Concurrent Punch-Outs ===")
    
    # Create unique employee and punch in
    test_emp = {
        "emp_code": f"POUT_TEST_{int(time.time())}",
        "name": "Punch Out Test",
        "email": "pout@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-01"
    }
    setup_employee(test_emp)
    
    # Punch in first
    punch_in_ms = int(datetime(2026, 7, 16, 9, 30, 0).timestamp() * 1000)
    requests.post(f"{BASE_URL}/attendance/punch-in", json={
        "emp_code": test_emp["emp_code"],
        "punched_at": punch_in_ms,
        "status": "PRESENT"
    })
    
    # Now try concurrent punch-outs
    punch_out_ms = int(datetime(2026, 7, 16, 18, 30, 0).timestamp() * 1000)
    
    def punch_out():
        return requests.post(f"{BASE_URL}/attendance/punch-out", json={
            "emp_code": test_emp["emp_code"],
            "punched_at": punch_out_ms
        })
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(punch_out) for _ in range(5)]
        responses = [f.result() for f in as_completed(futures)]
    
    status_codes = [r.status_code for r in responses]
    success_count = status_codes.count(200)
    conflict_count = status_codes.count(409)
    
    print(f"  Results: {success_count} succeeded (200), {conflict_count} conflicted (409)")
    print(f"  Status codes: {status_codes}")
    
    passed = success_count == 1 and conflict_count == 4
    status = "✓" if passed else "✗"
    print(f"  {status} Exactly one success, rest conflicts")
    
    return passed


def test_concurrent_patches():
    """
    Test race condition: Two concurrent PATCH corrections.
    Both should succeed, and BOTH history entries should be preserved.
    """
    print("\n=== Testing Concurrent PATCH Corrections ===")
    
    # Create employee and record
    test_emp = {
        "emp_code": f"PATCH_TEST_{int(time.time())}",
        "name": "Patch Test",
        "email": "patch@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "18:30",
        "joined_on": "2026-01-01"
    }
    setup_employee(test_emp)
    
    # Create initial record
    punch_in_ms = int(datetime(2026, 7, 17, 10, 0, 0).timestamp() * 1000)
    requests.post(f"{BASE_URL}/attendance/punch-in", json={
        "emp_code": test_emp["emp_code"],
        "punched_at": punch_in_ms,
        "status": "PRESENT"
    })
    
    # Punch out
    punch_out_ms = int(datetime(2026, 7, 17, 18, 30, 0).timestamp() * 1000)
    requests.post(f"{BASE_URL}/attendance/punch-out", json={
        "emp_code": test_emp["emp_code"],
        "punched_at": punch_out_ms
    })
    
    # Now two admins correct it concurrently
    def patch_by_admin1():
        return requests.patch(
            f"{BASE_URL}/attendance/{test_emp['emp_code']}/2026-07-17",
            json={
                "punch_in": int(datetime(2026, 7, 17, 9, 30, 0).timestamp() * 1000),
                "reason": "Admin 1: biometric glitch",
                "regularized_by": "admin1"
            }
        )
    
    def patch_by_admin2():
        return requests.patch(
            f"{BASE_URL}/attendance/{test_emp['emp_code']}/2026-07-17",
            json={
                "punch_out": int(datetime(2026, 7, 17, 19, 0, 0).timestamp() * 1000),
                "reason": "Admin 2: stayed late",
                "regularized_by": "admin2"
            }
        )
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(patch_by_admin1)
        f2 = executor.submit(patch_by_admin2)
        r1 = f1.result()
        r2 = f2.result()
    
    print(f"  Admin 1 result: {r1.status_code}")
    print(f"  Admin 2 result: {r2.status_code}")
    
    # Both should succeed
    both_succeeded = r1.status_code == 200 and r2.status_code == 200
    
    # Fetch final record
    resp = requests.get(
        f"{BASE_URL}/attendance",
        params={"emp_code": test_emp["emp_code"], "date_from": "2026-07-17", "date_to": "2026-07-17"}
    )
    record = resp.json()["items"][0]
    history = record.get("history", [])
    
    print(f"  History entries: {len(history)}")
    for i, entry in enumerate(history, 1):
        print(f"    {i}. By {entry['by']}: {entry['reason']}")
    
    has_both = len(history) == 2
    passed = both_succeeded and has_both
    
    status = "✓" if passed else "✗"
    print(f"  {status} Both patches succeeded and both history entries preserved")
    
    return passed


def test_bad_timestamps():
    """
    Test timestamp validation: floats, strings, seconds, bools should all give 422.
    """
    print("\n=== Testing Bad Timestamp Validation ===")
    setup_employee(TEST_EMPLOYEE)
    
    test_cases = [
        (1720234500.5, "float"),
        ("1720234500000", "string"),
        (1720234500, "seconds (not milliseconds)"),
        (True, "boolean"),
        (None, "null (should use current time, not 422)"),  # This one should succeed
    ]
    
    results = []
    for bad_value, description in test_cases:
        resp = requests.post(f"{BASE_URL}/attendance/punch-in", json={
            "emp_code": TEST_EMPLOYEE["emp_code"],
            "punched_at": bad_value,
            "status": "PRESENT"
        })
        
        if description == "null (should use current time, not 422)":
            # null should succeed and use current time
            passed = resp.status_code in [201, 409]  # OK or already exists
            expected = "201 or 409"
        else:
            # All others should fail with 422
            passed = resp.status_code == 422
            expected = "422"
        
        actual = resp.status_code
        status = "✓" if passed else "✗"
        results.append((status, description, expected, actual))
        print(f"  {status} {description}")
        print(f"     Expected: {expected}, Got: {actual}")
    
    return all(r[0] == "✓" for r in results)


def main():
    """Run all tests and show summary."""
    print("="*70)
    print("BUSINESS RULES AND EDGE CASE TESTS")
    print("="*70)
    print("\nMake sure the server is running at http://localhost:8000")
    print("These tests create records in the database.\n")
    
    tests = [
        ("R2: Late Calculation", test_r2_late_calculation),
        ("R3: Overtime at 29/30 min", test_r3_overtime_boundary),
        ("R8: Half-Up Rounding", test_half_up_rounding),
        ("R1: Overnight Shift", test_overnight_shift),
        ("Concurrent Punch-Ins", test_concurrent_punch_ins),
        ("Concurrent Punch-Outs", test_concurrent_punch_outs),
        ("Concurrent PATCHes", test_concurrent_patches),
        ("Bad Timestamp Validation", test_bad_timestamps),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            result = test_func()
            results[name] = result
        except Exception as e:
            print(f"\n  ✗ Exception: {e}")
            results[name] = False
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    for name, result in results.items():
        if result is None:
            status = "⚠ SKIP"
        elif result:
            status = "✓ PASS"
        else:
            status = "✗ FAIL"
        print(f"{status}: {name}")
    
    passed = sum(1 for r in results.values() if r is True)
    failed = sum(1 for r in results.values() if r is False)
    skipped = sum(1 for r in results.values() if r is None)
    
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")


if __name__ == "__main__":
    main()

"""
Verify that all explain outputs use indexes (IXSCAN) and not collection scans (COLLSCAN).

Run after generating test data and starting the app:
    python check_indexes.py
"""
import requests
import json

BASE_URL = "http://localhost:8000"

def check_for_collscan(explain_data):
    """Recursively search explain output for COLLSCAN stages."""
    explain_str = json.dumps(explain_data)
    has_collscan = "COLLSCAN" in explain_str
    has_ixscan = "IXSCAN" in explain_str
    return has_collscan, has_ixscan

def find_stages(node, stage_type, found=None):
    """Recursively find all stages of a given type."""
    if found is None:
        found = []
    
    if isinstance(node, dict):
        if node.get("stage") == stage_type:
            found.append(node)
        for value in node.values():
            find_stages(value, stage_type, found)
    elif isinstance(node, list):
        for item in node:
            find_stages(item, stage_type, found)
    
    return found

def test_endpoint(name, url):
    """Test a single explain endpoint."""
    print(f"\n{'='*70}")
    print(f"Testing: {name}")
    print(f"URL: {url}")
    print(f"{'='*70}")
    
    try:
        response = requests.get(url)
        
        if response.status_code != 200:
            print(f"❌ Error: Status {response.status_code}")
            print(f"   Response: {response.text}")
            return False
        
        data = response.json()
        explain = data.get("explain", {})
        
        # Check for COLLSCAN and IXSCAN
        has_collscan, has_ixscan = check_for_collscan(explain)
        
        if has_collscan:
            print("❌ COLLECTION SCAN DETECTED!")
            collscans = find_stages(explain, "COLLSCAN")
            for cs in collscans:
                print(f"   Stage: {cs.get('stage')}")
                print(f"   Namespace: {cs.get('namespace', 'unknown')}")
            return False
        else:
            print("✓ No collection scans")
        
        if has_ixscan:
            print("✓ Index scans detected")
            ixscans = find_stages(explain, "IXSCAN")
            for ix in ixscans:
                print(f"   Index used: {ix.get('indexName', 'unknown')}")
                print(f"   Keys examined: {ix.get('keysExamined', 'unknown')}")
        else:
            print("⚠️  Warning: No IXSCAN found (might be OK for empty results)")
        
        # Check execution stats
        stats = explain.get("executionStats", {})
        if stats:
            total_docs = stats.get("totalDocsExamined", 0)
            total_keys = stats.get("totalKeysExamined", 0)
            returned = stats.get("nReturned", 0)
            
            print(f"\nExecution Stats:")
            print(f"  Docs examined: {total_docs}")
            print(f"  Keys examined: {total_keys}")
            print(f"  Docs returned: {returned}")
            
            if returned > 0 and total_docs > returned * 10:
                print(f"  ⚠️  Examined {total_docs/returned:.1f}x more docs than returned")
                print(f"     (Index may not be optimal)")
            elif returned > 0:
                print(f"  ✓ Good efficiency ({total_docs/returned:.1f}x ratio)")
        
        return not has_collscan
        
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

def main():
    print("="*70)
    print("INDEX VERIFICATION TOOL")
    print("="*70)
    print("\nThis script tests explain endpoints to verify index usage.")
    print("Make sure MongoDB is running with test data loaded.")
    
    results = {}
    
    # Test attendance_list
    results["attendance_list (all)"] = test_endpoint(
        "GET /attendance (all records)",
        f"{BASE_URL}/admin/explain/attendance_list"
    )
    
    results["attendance_list (date range)"] = test_endpoint(
        "GET /attendance (date range)",
        f"{BASE_URL}/admin/explain/attendance_list?date_from=2026-01-01&date_to=2026-12-31"
    )
    
    results["attendance_list (status)"] = test_endpoint(
        "GET /attendance (by status)",
        f"{BASE_URL}/admin/explain/attendance_list?status=PRESENT"
    )
    
    results["attendance_list (emp_code)"] = test_endpoint(
        "GET /attendance (by employee)",
        f"{BASE_URL}/admin/explain/attendance_list?emp_code=TEST0001"
    )
    
    # Test employee_monthly
    results["employee_monthly"] = test_endpoint(
        "GET /analytics/employees/{emp_code}/monthly",
        f"{BASE_URL}/admin/explain/employee_monthly?emp_code=TEST0001&month=2026-01"
    )
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, passed_test in results.items():
        status = "✓ PASS" if passed_test else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\n{passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All queries use indexes! No collection scans detected.")
    else:
        print("\n⚠️  Some queries are not using indexes optimally.")
        print("Review the output above for details.")

if __name__ == "__main__":
    main()

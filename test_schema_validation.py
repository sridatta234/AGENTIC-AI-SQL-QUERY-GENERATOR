"""
Test script to verify schema validation is working properly
"""
from query_generator import generate_sql_query
from database import get_available_databases

def test_schema_validation():
    """Test various scenarios to ensure schema validation works"""
    
    print("=" * 60)
    print("SCHEMA VALIDATION TEST")
    print("=" * 60)
    
    # Get available databases
    databases = get_available_databases()
    if not databases:
        print("❌ No databases available for testing")
        return
    
    test_db = databases[0]
    print(f"\n📊 Testing with database: {test_db}")
    print("-" * 60)
    
    # Test cases
    test_cases = [
        {
            "name": "Valid SELECT query",
            "query": "Show all records from the first table",
            "should_pass": True
        },
        {
            "name": "Invalid table name",
            "query": "Select all from non_existent_table_xyz_123",
            "should_pass": False
        },
        {
            "name": "Valid CREATE TABLE",
            "query": "Create a new table called test_products with id and name columns",
            "should_pass": True
        },
        {
            "name": "Irrelevant query",
            "query": "What is the weather today?",
            "should_pass": False
        }
    ]
    
    results = []
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n🧪 Test {i}: {test['name']}")
        print(f"   Query: {test['query']}")
        
        result = generate_sql_query(test['query'], test_db)
        
        # Check if result is an error
        is_error = result is None or (isinstance(result, str) and result.startswith("ERROR"))
        passed = (not is_error) == test['should_pass']
        
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"   Expected: {'Success' if test['should_pass'] else 'Error'}")
        print(f"   Got: {'Success' if not is_error else 'Error'}")
        print(f"   Result: {status}")
        
        if is_error:
            print(f"   Error Message: {result}")
        else:
            print(f"   Generated SQL: {result[:100]}..." if len(result) > 100 else f"   Generated SQL: {result}")
        
        results.append({
            "test": test['name'],
            "passed": passed
        })
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    total = len(results)
    passed = sum(1 for r in results if r['passed'])
    failed = total - passed
    
    print(f"Total Tests: {total}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"Success Rate: {(passed/total)*100:.1f}%")
    
    print("\n" + "=" * 60)
    
    if failed == 0:
        print("🎉 All tests passed! Schema validation is working properly.")
    else:
        print("⚠️  Some tests failed. Please review the results above.")
    
    print("=" * 60)

if __name__ == "__main__":
    test_schema_validation()

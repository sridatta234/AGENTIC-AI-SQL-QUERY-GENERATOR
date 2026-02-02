from query_generator import generate_sql_query, build_graph

print("Testing Query Refinement...")

# Test Case 1: "delete a database" -> Should become DROP DATABASE
query1 = "delete a database named cricket_info"
print(f"\nInput: {query1}")

# We can inspect the graph state directly if we want, but let's just run the full generation
# The generation should succeed and produce "DROP DATABASE cricket_info;"
sql1 = generate_sql_query(query1)
print(f"Generated SQL: {sql1}")

# Test Case 2: "remove table" -> Should become DROP TABLE
query2 = "remove the table called old_users"
print(f"\nInput: {query2}")
sql2 = generate_sql_query(query2)
print(f"Generated SQL: {sql2}")

print("\nTest Complete.")

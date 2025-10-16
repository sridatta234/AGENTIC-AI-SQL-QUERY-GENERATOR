import os
import ollama # Import the ollama library
import sqlparse
import re
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from database import engine, get_schema, create_engine_for_database

load_dotenv()

# No API key configuration needed for Ollama

def clean_sql_output(response_text):
    """Removes markdown formatting and extracts the raw SQL query"""
    # Remove markdown code blocks
    clean_query = re.sub(r"```sql\n(.*?)\n```", r"\1", response_text, flags=re.DOTALL)
    clean_query = re.sub(r"```\n(.*?)\n```", r"\1", clean_query, flags=re.DOTALL)
    
    # Extract SQL query patterns for different types of operations
    sql_patterns = [
        r"(SELECT\s+.*?;)",           # SELECT queries
        r"(INSERT\s+INTO\s+.*?;)",    # INSERT queries  
        r"(UPDATE\s+.*?;)",           # UPDATE queries
        r"(DELETE\s+FROM\s+.*?;)",    # DELETE queries
        r"(CREATE\s+TABLE\s+.*?;)",   # CREATE TABLE queries
        r"(CREATE\s+INDEX\s+.*?;)",   # CREATE INDEX queries
        r"(ALTER\s+TABLE\s+.*?;)",    # ALTER TABLE queries
        r"(DROP\s+TABLE\s+.*?;)",     # DROP TABLE queries
        r"(DROP\s+INDEX\s+.*?;)",     # DROP INDEX queries
        r"(TRUNCATE\s+TABLE\s+.*?;)", # TRUNCATE queries
        r"(CREATE\s+DATABASE\s+.*?;)",# CREATE DATABASE queries
        r"(DROP\s+DATABASE\s+.*?;)",  # DROP DATABASE queries
    ]
    
    for pattern in sql_patterns:
        sql_match = re.search(pattern, clean_query, re.DOTALL | re.IGNORECASE)
        if sql_match:
            return sql_match.group(1).strip()
    
    # If no specific pattern matches, return the cleaned text
    return clean_query.strip()

def validate_sql_query(sql_query):
    """Validates the sql query syntax before execution."""
    try:
        parsed = sqlparse.parse(sql_query)
        if not parsed:
            return False, "Invalid SQL syntax."
        
        # Check if it's a valid SQL statement
        first_token = str(parsed[0].tokens[0]).upper().strip()
        valid_operations = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP', 'TRUNCATE']
        
        if not any(first_token.startswith(op) for op in valid_operations):
            return False, "Invalid SQL operation."
            
        return True, None
    except Exception as e:
        return False, str(e)

def get_sql_operation_type(sql_query):
    """Determines the type of SQL operation."""
    sql_query = sql_query.upper().strip()
    
    if sql_query.startswith('SELECT'):
        return 'SELECT'
    elif sql_query.startswith('INSERT'):
        return 'INSERT'
    elif sql_query.startswith('UPDATE'):
        return 'UPDATE'
    elif sql_query.startswith('DELETE'):
        return 'DELETE'
    elif sql_query.startswith('CREATE TABLE'):
        return 'CREATE_TABLE'
    elif sql_query.startswith('CREATE INDEX'):
        return 'CREATE_INDEX'
    elif sql_query.startswith('ALTER TABLE'):
        return 'ALTER_TABLE'
    elif sql_query.startswith('DROP TABLE'):
        return 'DROP_TABLE'
    elif sql_query.startswith('DROP INDEX'):
        return 'DROP_INDEX'
    elif sql_query.startswith('TRUNCATE'):
        return 'TRUNCATE'
    elif sql_query.startswith('CREATE DATABASE'):
        return 'CREATE_DATABASE'
    elif sql_query.startswith('DROP DATABASE'):
        return 'DROP_DATABASE'
    else:
        return 'UNKNOWN'

def generate_sql_query(nl_query, database_name=None):
    """Converts natural language query to an optimized SQL query for ALL SQL operations."""
    schema = get_schema(database_name)
    schema_text = "\n".join([f"{table}: {', '.join(columns)}" for table, columns in schema.items()])
    
    current_database = database_name or "default database"

    # Enhanced prompt to handle all SQL operations
    prompt = f"""
    You are an expert SQL developer specializing in MySQL. Convert the following natural language request into a complete, optimized MySQL query.
    
    You can generate ANY type of SQL operation including:
    - SELECT: Data retrieval with proper JOINs, WHERE conditions, GROUP BY, ORDER BY
    - INSERT: Adding new records with proper value formatting
    - UPDATE: Modifying existing records with WHERE conditions
    - DELETE: Removing records with proper WHERE conditions
    - CREATE TABLE: Table creation with appropriate data types, constraints, and indexes
    - CREATE INDEX: Index creation for performance optimization
    - ALTER TABLE: Table modifications (ADD/DROP columns, constraints, etc.)
    - DROP TABLE/INDEX: Removing tables or indexes
    - TRUNCATE: Emptying tables
    - CREATE/DROP DATABASE: Database operations
    
    Guidelines:
    - Use proper MySQL syntax and data types (VARCHAR, INT, DATETIME, etc.)
    - Include appropriate constraints (PRIMARY KEY, FOREIGN KEY, NOT NULL, UNIQUE)
    - For SELECT queries: Use efficient JOINs, proper indexing, and optimization
    - For INSERT queries: Use proper value formatting and handle data types correctly
    - For UPDATE/DELETE: Always include WHERE conditions to prevent accidental mass operations
    - For CREATE TABLE: Include proper data types, constraints, and consider indexes
    - Always end queries with semicolon (;)
    - Consider performance and best practices
    
    Current Database: {current_database}
    Database Schema:
    {schema_text}
    
    User Request: {nl_query}
    
    Generate the appropriate SQL query:
    """

    try:
        # Use the ollama.chat() method with enhanced system message
        response = ollama.chat(
            model='llama3', # Choose a model you have downloaded with Ollama
            messages=[
                {
                    "role": "system", 
                    "content": "You are an expert MySQL database developer. You can generate any type of SQL query including SELECT, INSERT, UPDATE, DELETE, CREATE TABLE, ALTER TABLE, DROP TABLE, CREATE INDEX, etc. Always provide complete, syntactically correct, and optimized SQL queries. Focus on performance and best practices."
                },
                {"role": "user", "content": prompt}
            ]
        )
        raw_sql_query = response['message']['content'].strip()
        clean_query = clean_sql_output(raw_sql_query)
        
        # Validate the generated query
        is_valid, error_msg = validate_sql_query(clean_query)
        if not is_valid:
            print(f"Generated query validation failed: {error_msg}")
            return None
            
        return clean_query
    
    except Exception as e:
        print(f"Error generating SQL query: {e}")
        return None

def suggest_optimization(sql_query, operation_type, database_name=None):
    """Suggests optimizations based on the SQL operation type."""
    suggestions = []
    
    # Use appropriate engine based on database selection
    target_engine = create_engine_for_database(database_name) if database_name else engine
    
    if operation_type == 'SELECT':
        try:
            with target_engine.connect() as connection:
                explain_query = f"EXPLAIN {sql_query}"
                result = connection.execute(text(explain_query))
                execution_plan = result.fetchall()

            # Analyze execution plan for SELECT queries
            for row in execution_plan:
                if hasattr(row, '_asdict'):
                    row_dict = row._asdict()
                elif hasattr(row, '_mapping'):
                    row_dict = dict(row._mapping)
                else:
                    row_dict = dict(row)
                
                if row_dict.get('type') == 'ALL':
                    suggestions.append("Consider adding an index - full table scan detected")
                if row_dict.get('key') is None and row_dict.get('possible_keys'):
                    suggestions.append("Potential index optimization available")
                if row_dict.get('Extra') and 'filesort' in str(row_dict.get('Extra')):
                    suggestions.append("Consider adding index for ORDER BY clause")
                    
        except Exception as e:
            suggestions.append(f"Could not analyze execution plan: {e}")
    
    elif operation_type in ['INSERT', 'UPDATE', 'DELETE']:
        suggestions.append("Ensure proper indexing on WHERE clause columns for optimal performance")
        if operation_type in ['UPDATE', 'DELETE']:
            suggestions.append("Always use WHERE conditions to avoid unintended mass operations")
            suggestions.append("Consider using transactions for data safety")
    
    elif operation_type == 'CREATE_TABLE':
        suggestions.append("Consider adding appropriate indexes on frequently queried columns")
        suggestions.append("Use proper data types and constraints for data integrity")
        suggestions.append("Consider partitioning for large tables")
    
    elif operation_type == 'CREATE_INDEX':
        suggestions.append("Monitor index usage and remove unused indexes")
        suggestions.append("Consider composite indexes for multi-column queries")
    
    elif operation_type in ['DROP_TABLE', 'DROP_INDEX', 'TRUNCATE']:
        suggestions.append("⚠️  CAUTION: This operation is irreversible. Ensure you have backups")
        suggestions.append("Consider using transactions and testing in development first")
    
    return " | ".join(suggestions) if suggestions else "No specific optimization suggestions for this query type."

def execute_query(sql_query, database_name=None):
    """Executes a validated and optimized SQL query of any type."""
    is_valid, error_msg = validate_sql_query(sql_query)
    if not is_valid:
        print(f"SQL Validation Error: {error_msg}")
        return None
    
    operation_type = get_sql_operation_type(sql_query)
    
    # Use appropriate engine based on database selection
    target_engine = create_engine_for_database(database_name) if database_name else engine
    
    try:
        with target_engine.connect() as connection:
            # Handle different types of operations
            if operation_type == 'SELECT':
                result = connection.execute(text(sql_query))
                fetched_results = result.fetchall()
            else:
                # For non-SELECT operations (INSERT, UPDATE, DELETE, etc.)
                result = connection.execute(text(sql_query))
                connection.commit()  # Ensure changes are committed
                
                # Create a summary result for non-SELECT operations
                if operation_type in ['INSERT', 'UPDATE', 'DELETE']:
                    rows_affected = result.rowcount if hasattr(result, 'rowcount') else 'Unknown'
                    fetched_results = [{'operation': operation_type, 'rows_affected': rows_affected, 'status': 'Success'}]
                else:
                    fetched_results = [{'operation': operation_type, 'status': 'Success', 'message': f'{operation_type} operation completed successfully'}]

        optimization_suggestions = suggest_optimization(sql_query, operation_type, database_name)

        return {
            "results": fetched_results, 
            "optimization_tips": optimization_suggestions,
            "operation_type": operation_type
        }
        
    except SQLAlchemyError as e:
        print(f"Database Execution Error: {str(e)}")
        return None

if __name__ == "__main__":
    print("=== Enhanced SQL Query Generator with Ollama ===")
    print("Supports all SQL operations: SELECT, INSERT, UPDATE, DELETE, CREATE TABLE, etc.")
    print()
    
    while True:
        user_input = input("\nEnter your natural language request (or 'quit' to exit): ")
        
        if user_input.lower() in ['quit', 'exit', 'q']:
            break
            
        sql_query = generate_sql_query(user_input)

        if sql_query:
            print(f"\nGenerated SQL Query:\n{sql_query}")
            
            # Ask user if they want to execute the query
            execute_choice = input("\nDo you want to execute this query? (y/n): ").lower()
            
            if execute_choice in ['y', 'yes']:
                execution_results = execute_query(sql_query)
                if execution_results:
                    print(f"\nOperation Type: {execution_results['operation_type']}")
                    print("\nQuery Results:")
                    for row in execution_results["results"]:
                        print(row)
                    print(f"\nOptimization Tips: {execution_results['optimization_tips']}")
                else:
                    print("Error executing query.")
            else:
                print("Query not executed.")
        else:
            print("Failed to generate a valid SQL query.")
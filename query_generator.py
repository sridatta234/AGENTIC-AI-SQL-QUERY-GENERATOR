import os
import ollama
import sqlparse
import re
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from database import engine, get_schema, create_engine_for_database

# Import optional APIs
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

load_dotenv()

# Configure LLM providers
LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'ollama').lower()
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')
GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama-3.1-8b-instant')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3')

# API Keys
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')

# Initialize Gemini if available
if GEMINI_AVAILABLE and GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

# Initialize Groq if available
if GROQ_AVAILABLE and GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)
else:
    groq_client = None

def call_llm(messages, system_prompt=None, provider=None):
    """Unified LLM calling function that routes to appropriate provider."""
    if provider is None:
        provider = LLM_PROVIDER
    
    try:
        # Try Groq first (fastest and most reliable)
        if provider == 'groq' and GROQ_AVAILABLE and groq_client:
            groq_messages = []
            if system_prompt:
                groq_messages.append({"role": "system", "content": system_prompt})
            groq_messages.extend(messages)
            
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=groq_messages,
                temperature=0.1,
                max_tokens=1024
            )
            return response.choices[0].message.content.strip()
        
        # Try Gemini
        elif provider == 'gemini' and GEMINI_AVAILABLE and GOOGLE_API_KEY:
            model = genai.GenerativeModel(
                model_name=GEMINI_MODEL,
                system_instruction=system_prompt
            )
            user_message = messages[-1]['content'] if messages else ""
            response = model.generate_content(user_message)
            return response.text.strip()
        
        # Fall back to Ollama
        else:
            ollama_messages = messages
            if system_prompt:
                ollama_messages = [{"role": "system", "content": system_prompt}] + messages
            
            response = ollama.chat(
                model=OLLAMA_MODEL,
                messages=ollama_messages
            )
            return response['message']['content'].strip()
            
    except Exception as e:
        # Smart fallback: Groq -> Gemini -> Ollama
        if provider == 'groq' and GEMINI_AVAILABLE and GOOGLE_API_KEY:
            print(f"Groq failed, trying Gemini: {e}")
            return call_llm(messages, system_prompt, provider='gemini')
        elif provider in ['groq', 'gemini']:
            print(f"{provider.title()} failed, falling back to Ollama: {e}")
            return call_llm(messages, system_prompt, provider='ollama')
        raise e

def clean_sql_output(response_text):
    """Removes markdown formatting and extracts the raw SQL query"""
    clean_query = re.sub(r"```sql\n(.*?)\n```", r"\1", response_text, flags=re.DOTALL)
    clean_query = re.sub(r"```\n(.*?)\n```", r"\1", clean_query, flags=re.DOTALL)
    
    sql_patterns = [
        r"(SELECT\s+.*?;)",
        r"(INSERT\s+INTO\s+.*?;)",
        r"(UPDATE\s+.*?;)",
        r"(DELETE\s+FROM\s+.*?;)",
        r"(CREATE\s+TABLE\s+.*?;)",
        r"(CREATE\s+INDEX\s+.*?;)",
        r"(ALTER\s+TABLE\s+.*?;)",
        r"(DROP\s+TABLE\s+.*?;)",
        r"(DROP\s+INDEX\s+.*?;)",
        r"(TRUNCATE\s+TABLE\s+.*?;)",
        r"(CREATE\s+DATABASE\s+.*?;)",
        r"(DROP\s+DATABASE\s+.*?;)",
    ]
    
    for pattern in sql_patterns:
        sql_match = re.search(pattern, clean_query, re.DOTALL | re.IGNORECASE)
        if sql_match:
            return sql_match.group(1).strip()
    
    return clean_query.strip()

def validate_sql_query(sql_query):
    """Validates the sql query syntax before execution."""
    try:
        parsed = sqlparse.parse(sql_query)
        if not parsed:
            return False, "Invalid SQL syntax."
        
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

def validate_query_relevance(nl_query, schema, database_name):
    """
    Uses LLM to check if the query is relevant to the database and uses valid schema elements.
    Returns (bool, str): (True, None) if valid, (False, error_message) if invalid.
    """
    schema_text = "\n".join([f"{table}: {', '.join(columns)}" for table, columns in schema.items()])
    
    validation_prompt = f"""
    You are a strict database guard. Analyze the user query against the provided database schema.
    
    Database: {database_name}
    Schema:
    {schema_text}
    
    User Query: "{nl_query}"
    
    INSTRUCTIONS:
    1. IDENTIFY OPERATION: Is this SELECT, INSERT, UPDATE, DELETE, or CREATE/DROP?
    
    2. IF SELECT / UPDATE / DELETE:
       - Check if the requested Tables and Columns exist in the schema.
       - STRICTLY MATCH specific types (e.g., "Test" vs "ODI", "Home" vs "Work").
       - REJECT if the specific column/table is missing.
       
    3. IF INSERT:
       - Check if the target Table exists.
       - Check if the target Columns exist.
       - ALLOW new data values (e.g., "Insert player named X" is VALID even if X isn't in DB).
       
    4. IF CREATE:
       - ALLOW creating new tables or columns.
       - Do NOT reject because the table doesn't exist yet (that's the point of CREATE).
    
    OUTPUT FORMAT (You must follow this exactly):
    Reasoning: [Explain your thought process. Identify the operation type first.]
    Status: [VALID | IRRELEVANT | INVALID_ENTITY]
    Error: [If invalid, provide the error message here. Otherwise leave empty.]
    """
    
    try:
        # Use a fast, direct call for validation
        response = call_llm(
            messages=[{"role": "user", "content": validation_prompt}],
            system_prompt="You are a validation system. You must reason step-by-step before deciding."
        )
        
        response = response.strip()
        
        # Parse the structured response
        status = "VALID"
        error_msg = None
        
        for line in response.split('\n'):
            if line.startswith("Status:"):
                status = line.split(":", 1)[1].strip().upper()
            if line.startswith("Error:"):
                error_msg = line.split(":", 1)[1].strip()
        
        if "IRRELEVANT" in status:
            return False, f"I cannot answer this. {error_msg or 'Query is unrelated to the database.'}"
            
        if "INVALID_ENTITY" in status:
            return False, f"I cannot generate SQL. {error_msg or 'The requested specific data type is missing from the schema.'}"
            
        return True, None
        
    except Exception as e:
        print(f"Validation check failed (proceeding anyway): {e}")
        return True, None

def generate_sql_query(nl_query, database_name=None):
    """Converts natural language query to an optimized SQL query."""
    schema = get_schema(database_name)
    
    # 1. Intelligent Validation Layer
    is_valid, error_msg = validate_query_relevance(nl_query, schema, database_name or "database")
    if not is_valid:
        return f"ERROR: {error_msg}"

    schema_text = "\n".join([f"{table}: {', '.join(columns)}" for table, columns in schema.items()])
    
    current_database = database_name or "default database"

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
    
    Here are some examples of how to handle complex queries. 
    ⚠️ NOTE: These examples use a sample 'Sakila' movie database. 
    You must ADAPT these SQL patterns (JOINs, Window Functions, etc.) to the CURRENT DATABASE SCHEMA provided above. 
    Do NOT use table names from the examples if they don't exist in the current schema.
    
    Example 1 (Aggregation & Joins):
    Q: "Find the name of each film category and the number of films within each category."
    SQL:
    SELECT c.name AS category_name, COUNT(fc.film_id) AS film_count
    FROM category c
    JOIN film_category fc ON c.category_id = fc.category_id
    GROUP BY c.name
    ORDER BY film_count DESC;
    
    Example 2 (Multi-Table Join):
    Q: "Calculate the total revenue generated by each store."
    SQL:
    SELECT s.store_id, SUM(p.amount) AS total_revenue
    FROM store s
    JOIN staff st ON s.store_id = st.store_id
    JOIN payment p ON st.staff_id = p.staff_id
    GROUP BY s.store_id;
    
    Example 3 (Window Functions):
    Q: "For each store, find the top 3 customers who have spent the most money."
    SQL:
    WITH CustomerSpending AS (
        SELECT c.store_id, c.customer_id, c.first_name, c.last_name, SUM(p.amount) AS total_spent
        FROM customer c
        JOIN payment p ON c.customer_id = p.customer_id
        GROUP BY c.store_id, c.customer_id, c.first_name, c.last_name
    ),
    RankedSpending AS (
        SELECT store_id, first_name, last_name, total_spent,
        DENSE_RANK() OVER (PARTITION BY store_id ORDER BY total_spent DESC) as ranking
        FROM CustomerSpending
    )
    SELECT * FROM RankedSpending WHERE ranking <= 3;
    
    Example 4 (Date Extraction):
    Q: "Get a monthly and yearly count of rentals."
    SQL:
    SELECT YEAR(rental_date) AS rental_year, MONTH(rental_date) AS rental_month, COUNT(rental_id) AS rental_count
    FROM rental
    GROUP BY YEAR(rental_date), MONTH(rental_date)
    ORDER BY rental_year DESC, rental_month DESC;
    
    Example 5 (Anti-Join / Not Exists):
    Q: "Find all films that have never been rented."
    SQL:
    SELECT f.title
    FROM film f
    LEFT JOIN inventory i ON f.film_id = i.film_id
    LEFT JOIN rental r ON i.inventory_id = r.inventory_id
    WHERE r.rental_id IS NULL;

    Example 6 (Top 1 Group Average):
    Q: "Find the film category that has the highest average rental rate."
    SQL:
    SELECT c.name AS category_name, AVG(f.rental_rate) AS average_rate
    FROM category c
    JOIN film_category fc ON c.category_id = fc.category_id
    JOIN film f ON fc.film_id = f.film_id
    GROUP BY c.name
    ORDER BY average_rate DESC
    LIMIT 1;
    
    Generate the appropriate SQL query:
    """

    try:
        system_prompt = "You are an expert MySQL database developer. You can generate any type of SQL query including SELECT, INSERT, UPDATE, DELETE, CREATE TABLE, ALTER TABLE, DROP TABLE, CREATE INDEX, etc. Always provide complete, syntactically correct, and optimized SQL queries. Focus on performance and best practices."
        
        raw_sql_query = call_llm(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=system_prompt
        )
        
        clean_query = clean_sql_output(raw_sql_query)
        
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
    target_engine = create_engine_for_database(database_name) if database_name else engine
    
    if operation_type == 'SELECT':
        try:
            with target_engine.connect() as connection:
                explain_query = f"EXPLAIN {sql_query}"
                result = connection.execute(text(explain_query))
                execution_plan = result.fetchall()

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
    target_engine = create_engine_for_database(database_name) if database_name else engine
    
    try:
        with target_engine.connect() as connection:
            if operation_type == 'SELECT':
                result = connection.execute(text(sql_query))
                fetched_results = result.fetchall()
            else:
                result = connection.execute(text(sql_query))
                connection.commit()
                
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
    provider_name = LLM_PROVIDER.upper()
    print(f"=== Enhanced SQL Query Generator (Using {provider_name}) ===")
    print()
    
    while True:
        user_input = input("\nEnter your natural language request (or 'quit' to exit): ")
        
        if user_input.lower() in ['quit', 'exit', 'q']:
            break
            
        sql_query = generate_sql_query(user_input)

        if sql_query:
            print(f"\nGenerated SQL Query:\n{sql_query}")
            
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

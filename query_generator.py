import os
import re
import sqlparse
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from database import engine, get_schema, create_engine_for_database

# LangChain & LangGraph Imports
from typing import TypedDict, Optional, List, Dict, Any
from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

# Configure LLM providers
LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'ollama').lower()
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')
GROQ_MODEL = os.getenv('GROQ_MODEL', 'llama-3.1-8b-instant')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3')

# API Keys
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')

def get_llm_model():
    """Returns a LangChain ChatModel with fallbacks configured."""
    
    # Define models
    ollama_model = ChatOllama(model=OLLAMA_MODEL, temperature=0.1)
    
    groq_model = None
    if GROQ_API_KEY:
        groq_model = ChatGroq(
            model=GROQ_MODEL, 
            temperature=0.1, 
            api_key=GROQ_API_KEY
        )
        
    gemini_model = None
    if GOOGLE_API_KEY:
        gemini_model = ChatGoogleGenerativeAI(
            model=GEMINI_MODEL, 
            temperature=0.1, 
            google_api_key=GOOGLE_API_KEY,
            convert_system_message_to_human=True
        )

    # Primary model selection based on env var
    primary_model = None
    fallbacks = []

    if LLM_PROVIDER == 'groq' and groq_model:
        primary_model = groq_model
        if gemini_model: fallbacks.append(gemini_model)
        fallbacks.append(ollama_model)
    elif LLM_PROVIDER == 'gemini' and gemini_model:
        primary_model = gemini_model
        if groq_model: fallbacks.append(groq_model)
        fallbacks.append(ollama_model)
    else:
        primary_model = ollama_model
        if groq_model: fallbacks.append(groq_model)
        if gemini_model: fallbacks.append(gemini_model)

    # Attach fallbacks if available
    if fallbacks:
        return primary_model.with_fallbacks(fallbacks)
    return primary_model

# --- Helper Functions ---

def clean_sql_output(response_text):
    """Removes markdown formatting and extracts the raw SQL query"""
    clean_query = re.sub(r"```sql\n(.*?)\n```", r"\1", response_text, flags=re.DOTALL)
    clean_query = re.sub(r"```\n(.*?)\n```", r"\1", clean_query, flags=re.DOTALL)
    
    sql_patterns = [
        r"(WITH\s+.*?;)",
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
        r"(SELECT\s+.*?;)",
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
        valid_operations = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'WITH']
        
        if not any(first_token.startswith(op) for op in valid_operations):
            return False, "Invalid SQL operation."
            
        return True, None
    except Exception as e:
        return False, str(e)

def get_sql_operation_type(sql_query):
    """Determines the type of SQL operation."""
    sql_query = sql_query.upper().strip()
    
    if sql_query.startswith('SELECT') or sql_query.startswith('WITH'): return 'SELECT'
    elif sql_query.startswith('INSERT'): return 'INSERT'
    elif sql_query.startswith('UPDATE'): return 'UPDATE'
    elif sql_query.startswith('DELETE'): return 'DELETE'
    elif sql_query.startswith('CREATE TABLE'): return 'CREATE_TABLE'
    elif sql_query.startswith('CREATE INDEX'): return 'CREATE_INDEX'
    elif sql_query.startswith('ALTER TABLE'): return 'ALTER_TABLE'
    elif sql_query.startswith('DROP TABLE'): return 'DROP_TABLE'
    elif sql_query.startswith('DROP INDEX'): return 'DROP_INDEX'
    elif sql_query.startswith('TRUNCATE'): return 'TRUNCATE'
    elif sql_query.startswith('CREATE DATABASE'): return 'CREATE_DATABASE'
    elif sql_query.startswith('DROP DATABASE'): return 'DROP_DATABASE'
    else: return 'UNKNOWN'

# --- LangGraph Agent Definition ---

class AgentState(TypedDict):
    nl_query: str
    refined_query: str  # Added for the cleaned/rephrased query
    database_name: str
    schema: Dict[str, List[str]]
    is_relevant: bool
    error_msg: Optional[str]
    sql_query: Optional[str]

def refine_query_node(state: AgentState):
    """Node to clean and rephrase the user query into precise technical language."""
    prompt = f"""
    You are a SQL expert assistant. Your job is to REPHRASE the user's request into precise, technical natural language that is easy to convert to SQL.
    
    User Request: "{state['nl_query']}"
    
    Guidelines:
    1. Correct terminology: 
       - "Delete database" -> "DROP DATABASE"
       - "Remove table" -> "DROP TABLE"
       - "Change column" -> "ALTER TABLE MODIFY COLUMN"
    2. Clarify intent: Ensure the action (SELECT, INSERT, etc.) is unambiguous.
    3. Keep it natural language: Do NOT generate SQL code yet. Just describe the action precisely.
    
    Example:
    Input: "delete a database named cricket_info"
    Output: "Drop the database named 'cricket_info'."
    
    Refined Request:
    """
    
    llm = get_llm_model()
    response = llm.invoke([
        SystemMessage(content="You are a helpful SQL assistant. Refine the user query for clarity and correctness."),
        HumanMessage(content=prompt)
    ])
    
    refined = response.content.strip()
    return {"refined_query": refined}

def check_relevance_node(state: AgentState):
    """Node to check query relevance against schema."""
    schema_text = "\n".join([f"{table}: {', '.join(columns)}" for table, columns in state['schema'].items()])
    
    # For INSERT operations, check if referenced data exists
    data_context = ""
    if "insert" in state['refined_query'].lower():
        # Try to detect which table is being inserted into
        import re
        insert_match = re.search(r'insert.*into\s+(\w+)', state['refined_query'], re.IGNORECASE)
        if insert_match:
            target_table = insert_match.group(1)
            # Check for potential foreign key references
            if target_table in state['schema']:
                # Get sample data from related tables to help the agent
                from database import create_engine_for_database
                from sqlalchemy import text
                target_engine = create_engine_for_database(state['database_name']) if state['database_name'] != "default database" else engine
                
                try:
                    with target_engine.connect() as connection:
                        # Get available data from potential parent tables
                        available_data = {}
                        for table_name in state['schema'].keys():
                            if table_name != target_table:
                                try:
                                    result = connection.execute(text(f"SELECT * FROM {table_name} LIMIT 5"))
                                    rows = result.fetchall()
                                    if rows:
                                        available_data[table_name] = len(rows)
                                except:
                                    pass
                        
                        if available_data:
                            data_context = f"\n\nAvailable data in related tables: {', '.join([f'{t} ({c} rows)' for t, c in available_data.items()])}"
                        else:
                            data_context = "\n\nWARNING: No data found in any related tables. Foreign key references may fail."
                except:
                    pass
    
    # Use the REFINED query for validation
    validation_prompt = f"""
    You are a strict database schema validator. Your job is to check if a user query is valid against the provided database schema.
    
    DATABASE INFORMATION:
    Database Name: {state['database_name']}
    
    AVAILABLE SCHEMA:
    {schema_text}{data_context}
    
    USER QUERY TO VALIDATE:
    "{state['refined_query']}"
    
    VALIDATION RULES:
    1. IDENTIFY the SQL operation type (SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, etc.)
    
    2. FOR SELECT/UPDATE/DELETE operations:
       - Check if ALL mentioned tables exist in the schema
       - Check if ALL mentioned columns exist in their respective tables
       - If any table or column is missing, return INVALID_ENTITY
    
    3. FOR INSERT operations:
       - Check if the target table exists in the schema
       - ALLOW new data values (they don't need to exist yet)
       - If the table has foreign key columns AND the data context shows no data in parent tables, return INVALID_ENTITY with error "Insufficient data: Parent table(s) are empty. Cannot create foreign key references."
       - Otherwise, ALLOW the insert
    
    4. FOR CREATE/DROP/ALTER operations:
       - ALLOW creating new tables/databases (they don't need to exist yet)
       - For DROP operations, check if the target exists
    
    5. FOR IRRELEVANT queries:
       - If the query is not related to databases or SQL, return IRRELEVANT
       - If the query asks about non-database topics, return IRRELEVANT
    
    OUTPUT FORMAT (You MUST follow this exact format):
    Status: [VALID | IRRELEVANT | INVALID_ENTITY]
    Error: [Specific error message if status is not VALID, otherwise leave empty]
    
    EXAMPLES:
    
    Example 1 - Valid SELECT:
    Query: "Show all customers"
    Schema has: customer table
    Output:
    Status: VALID
    Error: 
    
    Example 2 - Invalid table:
    Query: "Select from non_existent_table"
    Schema does NOT have: non_existent_table
    Output:
    Status: INVALID_ENTITY
    Error: Table 'non_existent_table' does not exist in schema
    
    Example 3 - Valid CREATE:
    Query: "Create a new table called products"
    Output:
    Status: VALID
    Error: 
    
    Now validate the user query above and provide your response:
    """
    
    llm = get_llm_model()
    response = llm.invoke([
        SystemMessage(content="You are a validation system. Reason step-by-step."),
        HumanMessage(content=validation_prompt)
    ])
    
    content = response.content.strip()
    status = "VALID"
    error_msg = None
    
    # Parse the response - handle various formats
    for line in content.split('\n'):
        line_lower = line.lower().strip()
        
        # Check for status (case-insensitive)
        if line_lower.startswith("status:"):
            status = line.split(":", 1)[1].strip().upper()
        
        # Check for error (case-insensitive)
        if line_lower.startswith("error:"):
            extracted_error = line.split(":", 1)[1].strip()
            # Only capture non-empty errors
            if extracted_error and extracted_error.lower() not in ['none', 'empty', 'n/a', '']:
                error_msg = extracted_error
    
    # Also check if status keywords appear anywhere in the response (fallback)
    content_upper = content.upper()
    if "INVALID_ENTITY" in content_upper or "INVALID ENTITY" in content_upper:
        status = "INVALID_ENTITY"
    elif "IRRELEVANT" in content_upper:
        status = "IRRELEVANT"
    elif "VALID" in content_upper and status == "VALID":
        status = "VALID"
    
    # Return based on status
    if "IRRELEVANT" in status:
        return {"is_relevant": False, "error_msg": f"I cannot answer this. {error_msg or 'Query is unrelated to the database.'}"}
    if "INVALID_ENTITY" in status or "INVALID" in status:
        return {"is_relevant": False, "error_msg": f"I cannot generate SQL. {error_msg or 'Requested data type missing from schema.'}"}
        
    return {"is_relevant": True, "error_msg": None}

def generate_sql_node(state: AgentState):
    """Node to generate the SQL query."""
    if not state['is_relevant']:
        return {} # Should not happen due to conditional edge, but safety check
        
    schema_text = "\n".join([f"{table}: {', '.join(columns)}" for table, columns in state['schema'].items()])
    
    # Load MySQL rules from file
    mysql_rules = ""
    try:
        rules_path = os.path.join(os.path.dirname(__file__), 'mysql_rules.md')
        with open(rules_path, 'r', encoding='utf-8') as f:
            mysql_rules = f.read()
    except:
        mysql_rules = "MySQL rules file not found. Using default rules."
    
    # Use the REFINED query for generation
    prompt = f"""
    You are an expert SQL developer specializing in MySQL. Convert the following natural language request into a complete, optimized MySQL query.
    
    Current Database: {state['database_name']}
    Database Schema:
    {schema_text}
    
    User Request: {state['refined_query']}
    
    Example 7 (Top N per Group - Correct Approach):
    Q: "For each store, find the top 3 customers who have spent the most money."
    SQL:
    WITH CustomerSpending AS (
        SELECT s.store_id, c.first_name, c.last_name, SUM(p.amount) AS total_spent,
        RANK() OVER (PARTITION BY s.store_id ORDER BY SUM(p.amount) DESC) as ranking
        FROM customer c
        JOIN payment p ON c.customer_id = p.customer_id
        JOIN store s ON c.store_id = s.store_id
        GROUP BY s.store_id, c.customer_id, c.first_name, c.last_name
    )
    SELECT * FROM CustomerSpending WHERE ranking <= 3;
    
    Example 8 (Delete Duplicates - Keep One Record):
    Q: "Delete duplicate records of 'Virat Kohli' from players table, keeping only one."
    SQL:
    DELETE FROM players
    WHERE player_id IN (
        SELECT player_id FROM (
            SELECT player_id, 
                   ROW_NUMBER() OVER (PARTITION BY full_name ORDER BY player_id) as rn
            FROM players
            WHERE full_name = 'Virat Kohli'
        ) AS duplicates
        WHERE rn > 1
    );
    
    
    IMPORTANT RULES:
    - You CANNOT delete from a CTE (Common Table Expression). CTEs are read-only.
    - Always DELETE FROM the actual table name, not from a CTE.
    - Use subqueries with ROW_NUMBER() to identify duplicates.
    - For INSERT statements: The columns in the schema are listed in their CORRECT ORDER. Respect this order.
    - For INSERT with foreign keys: MySQL does NOT support subqueries in VALUES clause.
    - WRONG: INSERT INTO matches VALUES (1, (SELECT team_id FROM teams WHERE...));
    - CORRECT: Use INSERT INTO ... SELECT with UNION ALL for multiple rows.
    - Example for matches table with team1_id and team2_id foreign keys:
      INSERT INTO matches (match_id, date, venue, team1_id, team2_id)
      SELECT 1, '2022-01-01', 'Mumbai', 
             (SELECT team_id FROM teams WHERE team_name='India'),
             (SELECT team_id FROM teams WHERE team_name='Australia')
      UNION ALL
      SELECT 2, '2022-01-15', 'Delhi',
             (SELECT team_id FROM teams WHERE team_name='India'),
             (SELECT team_id FROM teams WHERE team_name='Pakistan');
    - CRITICAL: Each SELECT must have the SAME number of columns as the INSERT column list.
    
    
    COMPREHENSIVE MYSQL RULES & BEST PRACTICES:
    {mysql_rules}
    
    Generate ANY type of SQL operation (SELECT, INSERT, UPDATE, DELETE, CREATE, etc.).
    - Use proper MySQL syntax.
    - Always end with semicolon (;).
    - Return ONLY the SQL query, wrapped in markdown ```sql ... ```.
    """
    
    llm = get_llm_model()
    response = llm.invoke([
        SystemMessage(content="You are an expert MySQL database developer. Provide complete, optimized SQL queries."),
        HumanMessage(content=prompt)
    ])
    
    clean_query = clean_sql_output(response.content)
    
    # Validate syntax immediately
    is_valid, error = validate_sql_query(clean_query)
    if not is_valid:
        return {"sql_query": None, "error_msg": f"Generated query validation failed: {error}"}
        
    return {"sql_query": clean_query}

def build_graph():
    workflow = StateGraph(AgentState)
    
    workflow.add_node("refine_query", refine_query_node)
    workflow.add_node("check_relevance", check_relevance_node)
    workflow.add_node("generate_sql", generate_sql_node)
    
    # Start with refinement
    workflow.set_entry_point("refine_query")
    
    # Then check relevance
    workflow.add_edge("refine_query", "check_relevance")
    
    def relevance_condition(state):
        if state['is_relevant']:
            return "generate_sql"
        return END
        
    workflow.add_conditional_edges(
        "check_relevance",
        relevance_condition
    )
    
    workflow.add_edge("generate_sql", END)
    
    return workflow.compile()

# --- Main Public API ---

def generate_sql_query(nl_query, database_name=None):
    """Converts natural language query to an optimized SQL query using LangGraph."""
    try:
        schema = get_schema(database_name)
        
        # Check if schema is empty (except for CREATE DATABASE operations)
        if not schema and not any(keyword in nl_query.lower() for keyword in ['create database', 'create schema']):
            db_name = database_name or "default database"
            return f"ERROR: No schema found for database '{db_name}'. The database may be empty or does not exist."
        
        app = build_graph()
        
        initial_state = {
            "nl_query": nl_query,
            "refined_query": None,
            "database_name": database_name or "default database",
            "schema": schema,
            "is_relevant": True, # Default assumption
            "error_msg": None,
            "sql_query": None
        }
        
        result = app.invoke(initial_state)
        
        if result.get("error_msg"):
            return f"ERROR: {result['error_msg']}"
            
        if not result.get("sql_query"):
            return "ERROR: Failed to generate SQL query."
            
        return result["sql_query"]
        
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
    print(f"=== Enhanced SQL Query Generator (Using {provider_name} via LangGraph) ===")
    print()
    
    while True:
        user_input = input("\nEnter your natural language request (or 'quit' to exit): ")
        
        if user_input.lower() in ['quit', 'exit', 'q']:
            break
            
        sql_query = generate_sql_query(user_input)

        if sql_query and not sql_query.startswith("ERROR"):
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
            print(f"Failed to generate a valid SQL query: {sql_query}")

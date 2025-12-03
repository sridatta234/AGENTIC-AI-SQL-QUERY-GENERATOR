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
    
    if sql_query.startswith('SELECT'): return 'SELECT'
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
    database_name: str
    schema: Dict[str, List[str]]
    is_relevant: bool
    error_msg: Optional[str]
    sql_query: Optional[str]

def check_relevance_node(state: AgentState):
    """Node to check query relevance against schema."""
    schema_text = "\n".join([f"{table}: {', '.join(columns)}" for table, columns in state['schema'].items()])
    
    validation_prompt = f"""
    You are a strict database guard. Analyze the user query against the provided database schema.
    
    Database: {state['database_name']}
    Schema:
    {schema_text}
    
    User Query: "{state['nl_query']}"
    
    INSTRUCTIONS:
    1. IDENTIFY OPERATION: Is this SELECT, INSERT, UPDATE, DELETE, or CREATE/DROP?
    2. IF SELECT / UPDATE / DELETE: Check if tables/columns exist. REJECT if missing.
    3. IF INSERT: Check if target table exists. ALLOW new data values.
    4. IF CREATE: ALLOW creating new tables.
    
    OUTPUT FORMAT (Strictly follow this):
    Status: [VALID | IRRELEVANT | INVALID_ENTITY]
    Error: [Error message if invalid, else empty]
    """
    
    llm = get_llm_model()
    response = llm.invoke([
        SystemMessage(content="You are a validation system. Reason step-by-step."),
        HumanMessage(content=validation_prompt)
    ])
    
    content = response.content.strip()
    status = "VALID"
    error_msg = None
    
    for line in content.split('\n'):
        if line.startswith("Status:"):
            status = line.split(":", 1)[1].strip().upper()
        if line.startswith("Error:"):
            error_msg = line.split(":", 1)[1].strip()
            
    if "IRRELEVANT" in status:
        return {"is_relevant": False, "error_msg": f"I cannot answer this. {error_msg or 'Query is unrelated to the database.'}"}
    if "INVALID_ENTITY" in status:
        return {"is_relevant": False, "error_msg": f"I cannot generate SQL. {error_msg or 'Requested data type missing from schema.'}"}
        
    return {"is_relevant": True, "error_msg": None}

def generate_sql_node(state: AgentState):
    """Node to generate the SQL query."""
    if not state['is_relevant']:
        return {} # Should not happen due to conditional edge, but safety check
        
    schema_text = "\n".join([f"{table}: {', '.join(columns)}" for table, columns in state['schema'].items()])
    
    prompt = f"""
    You are an expert SQL developer specializing in MySQL. Convert the following natural language request into a complete, optimized MySQL query.
    
    Current Database: {state['database_name']}
    Database Schema:
    {schema_text}
    
    User Request: {state['nl_query']}
    
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
    
    workflow.add_node("check_relevance", check_relevance_node)
    workflow.add_node("generate_sql", generate_sql_node)
    
    workflow.set_entry_point("check_relevance")
    
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
        app = build_graph()
        
        initial_state = {
            "nl_query": nl_query,
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

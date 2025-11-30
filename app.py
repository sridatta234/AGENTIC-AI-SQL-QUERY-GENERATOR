from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from query_generator import generate_sql_query, execute_query, get_sql_operation_type
from database import get_available_databases, get_database_info, get_schema

app = FastAPI(
    title="Enhanced AI SQL Query Generator",
    description="Generate and execute any type of SQL query using natural language with Ollama",
    version="2.0.0"
)

# Add CORS middleware for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class QueryRequest(BaseModel):
    query: str
    database: Optional[str] = None

class GenerateResponse(BaseModel):
    sql_query: Optional[str] = None
    error: Optional[str] = None
    operation_type: Optional[str] = None

class ExecuteResponse(BaseModel):
    results: list
    optimization_tips: str
    operation_type: str
    rows_affected: Optional[int] = None

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "Enhanced AI SQL Query Generator API",
        "description": "Generate and execute any type of SQL query using natural language",
        "supported_operations": [
            "SELECT", "INSERT", "UPDATE", "DELETE", 
            "CREATE TABLE", "ALTER TABLE", "DROP TABLE",
            "CREATE INDEX", "DROP INDEX", "TRUNCATE"
        ],
        "endpoints": {
            "generate_sql": "/generate_sql/",
            "execute_sql": "/execute_sql/",
            "databases": "/databases/",
            "database_info": "/database_info/{database_name}",
            "database_schema": "/database_schema/{database_name}"
        }
    }

@app.post("/generate_sql/", response_model=GenerateResponse)
async def generate_sql(request: QueryRequest):
    """Generate SQL query from natural language input for ANY SQL operation."""
    try:
        if not request.query.strip():
            return GenerateResponse(error="Query cannot be empty")
        
        sql_query = generate_sql_query(request.query, request.database)
        
        # Check for database relevance validation error
        if sql_query == "DATABASE_NOT_RELATED":
            return GenerateResponse(error="Missing database connection. Please specify the target database.")
        
        if not sql_query:
            return GenerateResponse(error="Failed to generate SQL query. Please try rephrasing your request.")
        
        operation_type = get_sql_operation_type(sql_query)
        return GenerateResponse(
            sql_query=sql_query,
            operation_type=operation_type
        )
    except Exception as e:
        return GenerateResponse(error=f"Error generating SQL: {str(e)}")

@app.post("/execute_sql/", response_model=ExecuteResponse)
async def execute_sql(request: QueryRequest):
    """Execute a given SQL query and return results with optimization tips."""
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="SQL query cannot be empty")
    
    sql_query = request.query.strip()
    operation_type = get_sql_operation_type(sql_query)
    
    try:
        results = execute_query(sql_query, request.database)
        if results is None:
            raise HTTPException(status_code=500, detail="Error executing query")
        
        # Handle different result formats based on operation type
        serialized_results = []
        rows_affected = None
        
        for row in results["results"]:
            if hasattr(row, '_mapping'):
                serialized_results.append(dict(row._mapping))
            elif isinstance(row, dict):
                serialized_results.append(row)
                if 'rows_affected' in row:
                    rows_affected = row['rows_affected']
            else:
                # Handle tuple results from SELECT queries
                try:
                    if hasattr(row, '_fields'):  # Named tuple
                        serialized_results.append(row._asdict())
                    else:
                        # Convert tuple to dict with column names
                        serialized_results.append({"result": str(row)})
                except:
                    serialized_results.append({"result": str(row)})
        
        return ExecuteResponse(
            results=serialized_results,
            optimization_tips=results["optimization_tips"],
            operation_type=results.get("operation_type", operation_type),
            rows_affected=rows_affected
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/databases/")
async def list_databases():
    """Get list of all available databases."""
    try:
        databases = get_available_databases()
        database_info = []
        
        for db_name in databases:
            info = get_database_info(db_name)
            database_info.append(info)
        
        return {
            "databases": database_info,
            "total_count": len(databases)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching databases: {str(e)}")

@app.get("/database_info/{database_name}")
async def get_database_details(database_name: str):
    """Get detailed information about a specific database."""
    try:
        info = get_database_info(database_name)
        schema = get_schema(database_name)
        
        return {
            "database_info": info,
            "schema": schema,
            "table_names": list(schema.keys())
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching database info: {str(e)}")

@app.get("/database_schema/{database_name}")
async def get_database_schema_only(database_name: str):
    """Get only the schema for a specific database."""
    try:
        schema = get_schema(database_name)
        return {
            "database": database_name,
            "schema": schema,
            "table_count": len(schema)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching schema: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
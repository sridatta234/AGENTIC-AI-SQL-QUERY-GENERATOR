import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

MYSQL_HOST=os.getenv("MYSQL_HOST")
MYSQL_USER=os.getenv("MYSQL_USER")
MYSQL_PASSWORD=os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE=os.getenv("MYSQL_DATABASE")
MYSQL_PORT=os.getenv("MYSQL_PORT","3306")

# Base connection without specific database for listing databases
BASE_DATABASE_URL = f"mysql+mysqlconnector://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}"
DATABASE_URL = f"mysql+mysqlconnector://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"

engine = create_engine(DATABASE_URL, echo=True)
base_engine = create_engine(BASE_DATABASE_URL, echo=True)


def test_connection():
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT DATABASE();"))
            print(f"Connected to: {result.fetchone()[0]}")
    except Exception as e:
        print(f"Error connecting to MySQL: {e}")


def get_available_databases():
    """Get list of all available databases"""
    query = """
    SELECT SCHEMA_NAME 
    FROM INFORMATION_SCHEMA.SCHEMATA 
    WHERE SCHEMA_NAME NOT IN ('information_schema', 'performance_schema', 'mysql', 'sys')
    ORDER BY SCHEMA_NAME;
    """
    
    try:
        with base_engine.connect() as connection:
            result = connection.execute(text(query))
            databases = [row[0] for row in result.fetchall()]
            return databases
    except Exception as e:
        print(f"Error fetching databases: {e}")
        return []

def create_engine_for_database(database_name):
    """Create engine for specific database"""
    if not database_name:
        return engine
    
    db_url = f"mysql+mysqlconnector://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{database_name}"
    return create_engine(db_url, echo=True)

def get_schema(database_name=None):
    """Get schema for specific database or default"""
    target_database = database_name or MYSQL_DATABASE
    query = """
    SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = :database;
    """

    # Use appropriate engine based on database selection
    target_engine = create_engine_for_database(database_name) if database_name else engine
    
    try:
        with target_engine.connect() as connection:
            result = connection.execute(text(query), {"database": target_database})
            schema_info = result.fetchall()

        schema_dict = {}
        for table, column, dtype in schema_info:
            if table not in schema_dict:
                schema_dict[table] = []
            schema_dict[table].append(f"{column} ({dtype})")
        return schema_dict
    except Exception as e:
        print(f"Error getting schema for database {target_database}: {e}")
        return {}

def get_database_info(database_name):
    """Get detailed information about a specific database"""
    try:
        target_engine = create_engine_for_database(database_name)
        
        # Get table count
        table_query = """
        SELECT COUNT(*) as table_count
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = :database;
        """
        
        # Get database size
        size_query = """
        SELECT 
            ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) AS size_mb
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = :database;
        """
        
        with target_engine.connect() as connection:
            table_result = connection.execute(text(table_query), {"database": database_name})
            table_count = table_result.fetchone()[0]
            
            size_result = connection.execute(text(size_query), {"database": database_name})
            size_mb = size_result.fetchone()[0] or 0
            
        return {
            "name": database_name,
            "table_count": table_count,
            "size_mb": float(size_mb)
        }
    except Exception as e:
        print(f"Error getting info for database {database_name}: {e}")
        return {
            "name": database_name,
            "table_count": 0,
            "size_mb": 0
        }

if __name__ == "__main__":
    test_connection()
    print("\nAvailable databases:")
    for db in get_available_databases():
        info = get_database_info(db)
        print(f"  {db} - {info['table_count']} tables, {info['size_mb']} MB")
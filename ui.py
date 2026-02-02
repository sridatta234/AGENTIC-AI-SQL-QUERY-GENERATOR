import streamlit as st
import requests
import json

# Page configuration
st.set_page_config(
    page_title="Enhanced AI SQL Generator",
    page_icon="🗄️",
    layout="wide"
)

st.title("🚀 Enhanced AI-Powered SQL Query Generator")
st.markdown("### Generate ANY type of SQL query using natural language with Ollama!")

# Show currently selected database
if "selected_database" in st.session_state and st.session_state["selected_database"]:
    st.info(f"🎯 **Active Database:** {st.session_state['selected_database']}")
else:
    st.info("🎯 **Active Database:** Default Configuration")

# Sidebar with instructions and examples
with st.sidebar:
    st.header("📋 Instructions")
    st.markdown("""
    This enhanced SQL generator can create:
    - **SELECT**: Data retrieval queries
    - **INSERT**: Add new records
    - **UPDATE**: Modify existing data
    - **DELETE**: Remove records
    - **CREATE TABLE**: Create new tables
    - **ALTER TABLE**: Modify table structure
    - **DROP TABLE**: Delete tables
    - **CREATE/DROP INDEX**: Manage indexes
    - **TRUNCATE**: Empty tables
    """)
    
    st.header("💡 Example Requests")
    example_queries = [
        "Show me all users from the users table",
        "Create a table for storing customer orders with id, customer_id, product, price, and order_date",
        "Insert a new user with name 'John Doe' and email 'john@example.com'",
        "Update the price of product 'Laptop' to 999.99",
        "Delete all orders older than 2022",
        "Add an index on the email column of users table",
        "Add a new column 'phone' to the users table"
    ]
    
    for i, example in enumerate(example_queries, 1):
        if st.button(f"Example {i}", key=f"example_{i}"):
            st.session_state["example_query"] = example

# Main content area with database selection
col1, col2 = st.columns([2, 1])

with col1:
    # Natural Language Query Input
    st.subheader("🗣️ Natural Language Input")
    
    # Use example query if selected
    default_query = st.session_state.get("example_query", "")
    query_input = st.text_area(
        "Describe what you want to do with your database:",
        value=default_query,
        height=100,
        placeholder="E.g., 'Create a table for storing blog posts with title, content, author, and creation date'"
    )
    
    # Clear example after use
    if "example_query" in st.session_state:
        del st.session_state["example_query"]
    
    generate_col1, generate_col2 = st.columns([1, 3])
    
    with generate_col1:
        generate_button = st.button("🔄 Generate SQL", type="primary")
    
    with generate_col2:
        if st.button("🧹 Clear All"):
            for key in list(st.session_state.keys()):
                if key.startswith(('generated_sql', 'operation_type', 'execution_result')):
                    del st.session_state[key]
            st.rerun()

with col2:
    # Status panel
    st.subheader("📊 Status")
    
    # API Status Check
    api_connected = False
    try:
        response = requests.get("http://127.0.0.1:8000/", timeout=5)
        if response.status_code == 200:
            st.success("✅ Backend API is running")
            api_info = response.json()
            if "supported_operations" in api_info:
                st.info(f"Supports: {', '.join(api_info['supported_operations'][:4])}...")
            api_connected = True
        else:
            st.error("❌ Backend API error")
    except requests.exceptions.RequestException:
        st.error("❌ Backend API not connected")
        st.warning("Make sure to start the FastAPI backend:\n`python app.py`")
    
    # Database Selection Panel
    st.subheader("🗄️ Database Selection")
    
    if api_connected:
        try:
            # Fetch available databases
            db_response = requests.get("http://127.0.0.1:8000/databases/", timeout=5)
            if db_response.status_code == 200:
                db_data = db_response.json()
                databases = db_data.get("databases", [])
                
                if databases:
                    # Create database options
                    db_options = ["Default"] + [db["name"] for db in databases]
                    
                    # Database selection dropdown
                    selected_db = st.selectbox(
                        "Select Database:",
                        options=db_options,
                        key="database_selection"
                    )
                    
                    # Store selected database
                    if selected_db != "Default":
                        st.session_state["selected_database"] = selected_db
                    else:
                        st.session_state["selected_database"] = None
                    
                    # Show database info
                    if selected_db != "Default":
                        selected_db_info = next((db for db in databases if db["name"] == selected_db), None)
                        if selected_db_info:
                            st.info(f"📊 **{selected_db}**\n"
                                   f"Tables: {selected_db_info['table_count']}\n"
                                   f"Size: {selected_db_info['size_mb']:.1f} MB")
                            
                            # Show schema button
                            if st.button(f"📋 Show {selected_db} Schema"):
                                try:
                                    schema_response = requests.get(f"http://127.0.0.1:8000/database_schema/{selected_db}")
                                    if schema_response.status_code == 200:
                                        schema_data = schema_response.json()
                                        st.session_state["current_schema"] = schema_data
                                except Exception as e:
                                    st.error(f"Error fetching schema: {e}")
                    else:
                        st.info("🔹 Using default database configuration")
                    
                    # Database List
                    st.subheader("📋 Available Databases")
                    for db in databases[:5]:  # Show first 5
                        with st.container():
                            cols = st.columns([3, 1])
                            with cols[0]:
                                st.text(f"📂 {db['name']}")
                            with cols[1]:
                                st.text(f"{db['table_count']}T")
                    
                    if len(databases) > 5:
                        st.text(f"... and {len(databases) - 5} more")
                        
                else:
                    st.warning("No databases found")
                    
            else:
                st.error("Failed to fetch databases")
                
        except Exception as e:
            st.error(f"Database connection error: {e}")
    else:
        st.warning("Connect to API to see databases")

# Generate SQL Logic
if generate_button and query_input.strip():
    with st.spinner("🤖 Generating SQL query..."):
        try:
            # Prepare request with selected database
            request_data = {"query": query_input}
            selected_database = st.session_state.get("selected_database")
            if selected_database:
                request_data["database"] = selected_database
            
            response = requests.post("http://127.0.0.1:8000/generate_sql/", json=request_data)
            data = response.json()

            if data.get("sql_query"):
                st.session_state["generated_sql"] = data["sql_query"]
                st.session_state["operation_type"] = data.get("operation_type", "UNKNOWN")
                st.success(f"✅ {data.get('operation_type', 'SQL')} query generated successfully!")
            else:
                st.error(f"❌ {data.get('error', 'SQL generation failed.')}")
                st.session_state["generated_sql"] = None
                
        except requests.exceptions.RequestException as e:
            st.error(f"🔌 Error connecting to backend: {e}")
        except json.JSONDecodeError:
            st.error("❌ Invalid response from backend")

elif generate_button and not query_input.strip():
    st.warning("⚠️ Please enter a description of what you want to do.")

# Display Generated SQL
if st.session_state.get("generated_sql"):
    st.subheader("📝 Generated SQL Query")
    
    operation_type = st.session_state.get("operation_type", "UNKNOWN")
    
    # Color code different operations
    if operation_type.startswith("SELECT"):
        st.info(f"🔍 **Operation Type:** {operation_type} (Data Retrieval)")
    elif operation_type.startswith("INSERT"):
        st.success(f"➕ **Operation Type:** {operation_type} (Add Data)")
    elif operation_type.startswith("UPDATE"):
        st.warning(f"✏️ **Operation Type:** {operation_type} (Modify Data)")
    elif operation_type.startswith("DELETE"):
        st.error(f"🗑️ **Operation Type:** {operation_type} (Remove Data)")
    elif operation_type.startswith("CREATE"):
        st.info(f"🏗️ **Operation Type:** {operation_type} (Create Structure)")
    elif operation_type.startswith("DROP"):
        st.error(f"💥 **Operation Type:** {operation_type} (Delete Structure)")
    else:
        st.info(f"⚙️ **Operation Type:** {operation_type}")
    
    st.code(st.session_state["generated_sql"], language="sql")
    
    # Execution buttons
    execute_col1, execute_col2 = st.columns([1, 1])
    
    with execute_col1:
        if st.button("▶️ Execute Query", type="primary"):
            with st.spinner("🏃 Executing SQL query..."):
                try:
                    # Prepare execution request with selected database
                    execute_data = {"query": st.session_state["generated_sql"]}
                    selected_database = st.session_state.get("selected_database")
                    if selected_database:
                        execute_data["database"] = selected_database
                    
                    response = requests.post(
                        "http://127.0.0.1:8000/execute_sql/", 
                        json=execute_data
                    )
                    data = response.json()
                    st.session_state["execution_result"] = data
                    
                except requests.exceptions.RequestException as e:
                    st.error(f"🔌 Error executing SQL: {e}")
                except json.JSONDecodeError:
                    st.error("❌ Invalid response from execution endpoint")
    
    with execute_col2:
        if st.button("📋 Copy to Manual Editor"):
            st.session_state["manual_sql"] = st.session_state["generated_sql"]
            st.success("📝 Copied to manual editor below!")

# Display Current Database Schema
if st.session_state.get("current_schema"):
    schema_data = st.session_state["current_schema"]
    st.subheader(f"📋 Schema: {schema_data['database']}")
    
    schema = schema_data.get("schema", {})
    if schema:
        # Create expandable sections for each table
        for table_name, columns in schema.items():
            with st.expander(f"📊 Table: {table_name}"):
                for column in columns:
                    st.text(f"  • {column}")
    else:
        st.info("No tables found in selected database")

# Display Execution Results
if st.session_state.get("execution_result"):
    result_data = st.session_state["execution_result"]
    
    st.subheader("📊 Execution Results")
    
    # Show operation summary
    operation_type = result_data.get("operation_type", "UNKNOWN")
    rows_affected = result_data.get("rows_affected")
    
    if rows_affected is not None:
        st.metric("Rows Affected", rows_affected)
    
    # Show results
    results = result_data.get("results", [])
    if results:
        if operation_type.startswith("SELECT"):
            st.dataframe(results, use_container_width=True)
        else:
            # For non-SELECT operations, show a clear success message
            if operation_type in ['INSERT', 'UPDATE', 'DELETE']:
                if rows_affected is not None and rows_affected > 0:
                    st.success(f"✅ {operation_type} operation completed successfully! {rows_affected} row(s) affected.")
                elif rows_affected == 0:
                    st.warning(f"⚠️ {operation_type} operation completed but no rows were affected.")
                else:
                    st.success(f"✅ {operation_type} operation completed successfully!")
            else:
                # For CREATE, DROP, etc.
                st.success(f"✅ {operation_type} operation completed successfully!")
            
            # Show the detailed status in an expander
            with st.expander("📋 View Detailed Status"):
                st.json(results)
    else:
        st.info("No data returned from query execution.")
    
    # Show optimization tips
    tips = result_data.get("optimization_tips", "No optimization tips.")
    if tips and tips != "No optimization tips.":
        st.subheader("💡 Optimization Tips")
        st.info(tips)

# Manual SQL Execution Section
st.subheader("✏️ Manual SQL Editor")
st.markdown("*For advanced users or query modifications*")

manual_sql = st.text_area(
    "Enter or paste your SQL query:",
    value=st.session_state.get("manual_sql", ""),
    height=150,
    key="manual_sql_input"
)

if st.button("▶️ Execute Manual SQL"):
    if manual_sql.strip():
        with st.spinner("🏃 Executing manual SQL query..."):
            try:
                # Prepare manual execution request with selected database
                manual_execute_data = {"query": manual_sql}
                selected_database = st.session_state.get("selected_database")
                if selected_database:
                    manual_execute_data["database"] = selected_database
                
                response = requests.post("http://127.0.0.1:8000/execute_sql/", json=manual_execute_data)
                data = response.json()

                st.subheader("📊 Manual Query Results")
                
                results = data.get("results", [])
                tips = data.get("optimization_tips", "No optimization tips.")
                operation_type = data.get("operation_type", "UNKNOWN")
                
                st.info(f"**Operation Type:** {operation_type}")
                
                if results:
                    if operation_type.startswith("SELECT"):
                        st.dataframe(results, use_container_width=True)
                    else:
                        st.json(results)
                else:
                    st.info("No data returned from query execution.")
                
                if tips and tips != "No optimization tips.":
                    st.subheader("💡 Optimization Tips")
                    st.info(tips)
                    
            except requests.exceptions.RequestException as e:
                st.error(f"🔌 Error executing SQL: {e}")
            except json.JSONDecodeError:
                st.error("❌ Invalid response from backend")
    else:
        st.warning("⚠️ Please enter a SQL query before executing.")

# Footer
st.markdown("---")
st.markdown("🤖 **Powered by Ollama & Llama3** | Built with Streamlit & FastAPI")
# Agentic AI SQL Generator - Workflow Diagram

```mermaid
graph TD
    User([User Input]) --> UI[Streamlit UI / FastAPI]
    UI --> LG_Start((LangGraph Start))

    subgraph "LangGraph Agent Workflow"
        LG_Start --> Refine[Refine Query Node]
        Refine -->|Refined NL Query| Validate[Check Relevance Node]
        
        Validate -->|Valid| Generate[Generate SQL Node]
        Validate -->|Invalid/Irrelevant| Error([Return Error])
        
        Generate -->|SQL Query| SyntaxCheck{Syntax Check}
        SyntaxCheck -->|Valid| Output[Final SQL Output]
        SyntaxCheck -->|Invalid| Error
    end

    Output --> Execution{Execute Query?}
    
    subgraph "Execution & Optimization"
        Execution -->|Yes| RunDB[(Database Execution)]
        RunDB --> Results[Fetch Results]
        RunDB --> Explain[EXPLAIN Analysis]
        Explain --> Optimize[Generate Optimization Tips]
    end

    Results --> FinalDisplay([Display Results & Tips])
    Optimize --> FinalDisplay
    Execution -->|No| FinalDisplay

    style Refine fill:#f9f,stroke:#333,stroke-width:2px
    style Validate fill:#ff9,stroke:#333,stroke-width:2px
    style Generate fill:#9f9,stroke:#333,stroke-width:2px
    style RunDB fill:#9cf,stroke:#333,stroke-width:2px
```

## Workflow Steps

1.  **User Input**: The user provides a natural language request (e.g., "Show top 3 customers").
2.  **Refine Query Node**: The agent rephrases the input into precise technical language (e.g., "delete database" -> "DROP DATABASE").
3.  **Check Relevance Node**: A strict validator checks if the requested tables/columns actually exist in the schema.
4.  **Generate SQL Node**: An expert LLM converts the refined request into optimized SQL (handling complex logic like CTEs and Window Functions).
5.  **Execution**: If approved, the query is executed against the connected database.
6.  **Optimization**: The system runs an `EXPLAIN` plan to provide performance tips (e.g., "Add index on column X").

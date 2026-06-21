
 - init.py
    - get_agent()
 
 - agent.py
  - run()
  - act()

 - tool_base.py
   - BaseTool

 - app_tools.py
   - delete_file

 - callbacks.py

 - context.py
   - ExecContext
     - event
     - state
   - AgentResult
     - status
     - pending_tc
  
 - llm_client.py
   - MessageHelper
 
 - rag.py

 - memory/*

 - context.py
   - PendingToolCall
   - ToolConfirmation


## uv
  - uv add chromadb
  - uv add scikit-learn
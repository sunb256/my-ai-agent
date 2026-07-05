
proxy
 - src/frontend/web/vite.config.ts proxy周り

docker機能
 - uv add uvicorn[standard]>=0.49.0
 - .env
 - .env.prod
 - infra/docker/
 - src/agent/core/agent.py  setup_code_env周り
 - src/agent/core/docker_code_env.py
 - .dockerignore
 - src/agent/init.py
 - src/agent/tests/test_init.py
 - src/api/main.py env周り
 - uv.lock

syntax highlight機能
npm i @monaco-editor/react  monaco-editor": "^0.55.1",
 - src/frontend/web/src/components/assistant-ui/tool-fallback.tsx
 - src/frontend/web/src/components/assistant-ui/tool-group.tsx
 - src/frontend/web/src/lib/monaco.ts
 - src/frontend/web/src/components/assistant-ui/markdown-text.tsx


file attach機能
 - src/frontend/web/src/runtime/attachmentAdapter.tsx
 - src/frontend/web/src/components/assistant-ui/thread.tsx
 - src/frontend/web/src/runtime/MyRuntimeProvider.tsx
 - src/frontend/web/src/components/assistant-ui/attachment.tsx
       <Avatar className="aui-attachment-tile-avatar h-full w-full rounded-none after:border-border/20">
        className="aui-attachment-tile bg-muted size-14 cursor-pointer overflow-hidden rounded-[calc(var(--composer-radius)-var(--composer-padding))] border border-border/40 transition-opacity hover:opacity-75"

------------------------------------------


 - src/agent/core/model/context.py
 - src/agent/core/model/llm_message.py

 - src/agent/core/llm_client.py
    - _build_kwargs
    - _merge_tool_name

 - src/agent/core/skills.py
    - select_requested_skills
    - make_requested_skills_prompt

 - src/agent/core/agent.py
    - _StepComplete
    - run
    - stream
    - _run_loop
    - step
    - _step_loop
    - _run_before_llm_cb
    - _apply_llm_response
    - _tool_results_since
    - _get_request(skill関係), _last_user_text
    - _tool_rets_output

 - api
    - src/api/event_factory.py
    - src/api/service.py
    - src/api/main.py
  
  - web
    - src/frontend/web/src/components/assistant-ui/thread.tsx
    - src/frontend/web/src/index.css
    - src/frontend/web/src/components/AgUiInterruptCard.tsx
    - src/frontend/web/src/components/AgUiInterruptPanel.tsx
    - src/frontend/web/src/runtime/MyRuntimeProvider.tsx
    - src/frontend/web/src/App.tsx

    - src/frontend/web/src/lib/utils.ts
    - src/frontend/web/tsconfig.json
    - src/frontend/web/tsconfig.app.json
    - src/frontend/web/vite.config.ts
    - src/frontend/web/.env.local


------------------------------------------

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
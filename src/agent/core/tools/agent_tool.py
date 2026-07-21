

from pathlib import Path

from agent.core.agent import Agent
from agent.core.code_exec import bash_tool, exec_python, upload_file
from agent.init import get_client, load_config


config = load_config(Path(""))
client = get_client(config)

researcher = Agent(
    client=client,
    role="researcher",
    desc="search the web and summarize finding on tany topic",
    system_prompt="you are a research specialist. use web_search to find relevant information. summarize your findings concisely",
    tools=[search_web],
    is_code_exec=False,
)

coder = Agent(
    client=client,
    role="coder",
    desc="write adn execute python code for data analysis and visualization",
    system_prompt="you are a python expert. werite clean, working code. execute code to verify results",
    tools=[exec_python, bash_tool, upload_file]
    is_code_exec=True,
)

from autogen import config_list_from_json, UserProxyAgent, GroupChat, GroupChatManager
from autogen.agentchat.contrib.gpt_assistant_agent import GPTAssistantAgent
from ai_svc.tool import web_scraping, google_search

config_list = config_list_from_json("OAI_CONFIG_LIST")

llm_config = {
    "config_list": config_list,
    "cache_seed": 42,
    "timeout": 1200,
    "temperature": 0
}

user_proxy = UserProxyAgent(
    name="user_proxy",
    system_message="A human administrator who put requirements, and runs the code provided by researcher.",
    is_termination_msg=lambda msg: "TERMINATE" in msg["content"],
    human_input_mode="ALWAYS",
    max_consecutive_auto_reply=1,
)

# Create researcher agent
researcher = GPTAssistantAgent(
    name="researcher",
    llm_config=llm_config | {
        "assistant_id": "asst_zRjKTMpcH62eg4o0hBmzLOlN"
    },
)

researcher.register_function(
    function_map={
        "web_scraping": web_scraping,
        "google_search": google_search,
    }
)

# Create research manager agent
research_manager = GPTAssistantAgent(
    name="research_manager",
    llm_config = llm_config | {
        "assistant_id": "asst_LEBKh6slRzBvaY9FEAi9fNv4"
    }
)


# Create director agent
director = GPTAssistantAgent(
    name = "director",
    llm_config = llm_config | {
        "assistant_id": "asst_A0jalYvQOQdLJJMNus8WLBak",
    }
)

# Create group chat
group_chat = GroupChat(agents=[
    user_proxy,
    researcher,
    research_manager,
    director,
], messages=[], max_round=15)
group_chat_manager = GroupChatManager(groupchat=group_chat, llm_config=llm_config)

# ---- Start Conversation ---- #
message = """
I wanna know the stock price change of MicroStrategy over the past month, get me the data by day.
"""
user_proxy.initiate_chat(group_chat_manager, message=message)
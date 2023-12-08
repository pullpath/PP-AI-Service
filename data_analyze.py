from autogen import config_list_from_json, UserProxyAgent, GroupChat, GroupChatManager, AssistantAgent

config_list = config_list_from_json("OAI_CONFIG_LIST")

llm_config = {
    "config_list": config_list,
    "timeout": 1200,
    "cache_seed": None,
    "temperature": 0
}

user_proxy = UserProxyAgent(
    name="user_proxy",
    system_message="A human administrator who proposes ideas, and runs the code provided by programmer.",
    code_execution_config={"work_dir": "data_analyze", "last_n_messages": 2, "use_docker": False},
    is_termination_msg=lambda msg: "TERMINATE" in msg["content"],
    human_input_mode="NEVER",
    max_consecutive_auto_reply=10,
)

# product_manager = AssistantAgent(
#     name="product_manager",
#     system_message="""You are a product manager, you will break down the initial ideas into a well scoped requirement for the programmer.
#     DO NOT get involved in any future conversation and error fixing.
#     """,
#     llm_config=llm_config,
# )

programmer = AssistantAgent(
    name="programmer",
    llm_config=llm_config
)

# Create group chat
# group_chat = GroupChat(agents=[
#     user_proxy,
#     product_manager,
#     programmer
# ], messages=[], max_round=15)
# group_chat_manager = GroupChatManager(groupchat=group_chat, llm_config=llm_config)

# ---- Start Conversation ---- #
message = """
Plot a chart of MSTR stock price change YTD.
"""
user_proxy.initiate_chat(programmer, message=message)
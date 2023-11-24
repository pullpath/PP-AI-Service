from langchain.chat_models import ChatOpenAI
from langchain.schema import HumanMessage
from langchain.prompts import ChatPromptTemplate
from langchain.schema.output_parser import StrOutputParser
from dotenv import load_dotenv
import os

load_dotenv()

openai_api_key = os.getenv('OPENAI_API_KEY')
openai_api_base = os.getenv('OPENAI_API_BASE')
openai_proxy_token = os.getenv('X-PP-TOKEN')

class OpenAIIntegration:
    def __init__(self):
        # Initialize the ChatOpenAI model
        self.chat_model = ChatOpenAI(model_name="gpt-3.5-turbo", openai_api_base=openai_api_base, openai_api_key=openai_api_key, default_headers={"x-pp-token": openai_proxy_token})

    def generate_text(self, text):
        # Use the chain to generate text
        prompt = ChatPromptTemplate.from_messages([
            HumanMessage(content=text)
        ])
        chain = prompt | self.chat_model | StrOutputParser()
        return chain.invoke({})
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage
from langchain.prompts import ChatPromptTemplate
from langchain.schema.output_parser import StrOutputParser
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.prompts import PromptTemplate
from langchain.chains.summarize import load_summarize_chain

from dotenv import load_dotenv
import os

load_dotenv()

openai_api_key = os.getenv('OPENAI_API_KEY')
openai_api_base = os.getenv('OPENAI_API_BASE')
openai_proxy_token = os.getenv('X-PP-TOKEN')

class OpenAIIntegration:
    def __init__(self, model_name=None):
        # Initialize the ChatOpenAI model
        if model_name is None:
            model_name = 'gpt-3.5-turbo'
        if openai_proxy_token is None:
            self.chat_model = ChatOpenAI(model_name=model_name, openai_api_key=openai_api_key, temperature=0)
        else:
            self.chat_model = ChatOpenAI(model_name=model_name, openai_api_base=openai_api_base, openai_api_key=openai_api_key, default_headers={"x-pp-token": openai_proxy_token}, temperature=0)

    def generate_text(self, text):
        # Use the chain to generate text
        prompt = ChatPromptTemplate.from_messages([
            HumanMessage(content=text)
        ])
        chain = prompt | self.chat_model | StrOutputParser()
        return chain.invoke({})
    
    def summary(self, objective, content):
        text_splitter = RecursiveCharacterTextSplitter(separators=["\n\n", "\n"], chunk_size = 10000, chunk_overlap=500)
        docs = text_splitter.create_documents([content])
        
        map_prompt = """
        Write a summary of the following text for {objective}:
        "{text}"
        SUMMARY:
        """
        map_prompt_template = PromptTemplate(template=map_prompt, input_variables=["text", "objective"])
        
        summary_chain = load_summarize_chain(
            llm=self.chat_model, 
            chain_type='map_reduce',
            map_prompt = map_prompt_template,
            combine_prompt = map_prompt_template,
            verbose = False
        )

        output = summary_chain.run(input_documents=docs, objective=objective)

        return output

    def audio_to_text(self, audio):
        from openai import OpenAI
        if openai_proxy_token is None:
            client = OpenAI(api_key=openai_api_key)
        else:
            client = OpenAI(api_key=openai_api_key, base_url=openai_api_base, default_headers={"x-pp-token": openai_proxy_token})
            
        audio_file= open(audio, "rb")
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )
        return transcript.text
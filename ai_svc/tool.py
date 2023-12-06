import json
import requests
from bs4 import BeautifulSoup
from .openai import OpenAIIntegration

from dotenv import load_dotenv
import os

load_dotenv()

serper_api_key = os.getenv('SERPER_API_KEY')
browserless_api_key = os.getenv('BROWSERLESS_API_KEY')

def google_search(keyword: str) -> str:
    url = "https://google.serper.dev/search"

    payload = json.dumps({
        "q": keyword
    })

    headers = {
        'X-API-KEY': serper_api_key,
        'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, headers=headers, data=payload)
    print("RESPONSE:", response.text)

    return response.text

def web_scraping(objective: str, url: str):
    #scrape website, and also will summarize the content based on objective if the content is too large
    #objective is the original objective & task that user give to the agent, url is the url of the website to be scraped

    print("Scraping website...")
    # Define the headers for the request
    headers = {
        'Cache-Control': 'no-cache',
        'Content-Type': 'application/json',
    }

    # Define the data to be sent in the request
    data = {
        "url": url        
    }

    # Convert Python object to JSON string
    data_json = json.dumps(data)

    # Send the POST request
    response = requests.post(f"https://chrome.browserless.io/content?token={browserless_api_key}", headers=headers, data=data_json)

    openai_integration = OpenAIIntegration()
    
    # Check the response status code
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, "html.parser")
        text = soup.get_text()
        print("CONTENTTTTTT:", text)
        print(len(text))
        if len(text) > 10000:
            output = openai_integration.summary(objective,text)
            return output
        else:
            return text
    else:
        print(f"HTTP request failed with status code {response.status_code}")   
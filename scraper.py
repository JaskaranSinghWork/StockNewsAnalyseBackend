from bs4 import BeautifulSoup
import requests

def scrape_articles(stock_symbol):
    url = f'https://news.example.com/search?q={stock_symbol}'
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    articles = []
    for item in soup.find_all('div', class_='article'):
        title = item.find('h2').text
        content = item.find('p').text
        articles.append({'title': title, 'content': content})
    
    return articles

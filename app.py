from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
import time
import re
from dotenv import load_dotenv
import os
import logging
import yfinance as yf
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# Load environment variables and configure logging
load_dotenv()
logging.basicConfig(level=logging.INFO)

# Configure Google AI
#GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GOOGLE_API_KEY = 'AIzaSyDrL9Q3HdH5uOTgY146W6rkcv-iEj9UAu0'
if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY not found in environment variables")
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Initialize Flask app
app = Flask(__name__)
CORS(app)

PROXIES = {
    "http": "http://your_proxy_url",
    "https": "finviz.com",
}
requests.get('https://google.com', verify=False)

# Constants
MAX_RETRIES = 3
RETRY_DELAY = 2
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

@app.route('/stock_suggestions', methods=['GET'])
def stock_suggestions():
    query = request.args.get('query', '').upper()
    if len(query) < 2:
        return jsonify({'suggestions': []})

    try:
        tickers = yf.Ticker(query).info
        if 'symbol' in tickers:
            suggestions = [tickers['symbol']]
        else:
            suggestions = list(tickers.keys())[:5]  # Limit to 5 suggestions
        return jsonify({'suggestions': suggestions})
    except Exception as e:
        logging.error(f"Error fetching stock suggestions: {str(e)}")
        return jsonify({'suggestions': []})

@app.route('/search_articles', methods=['POST'])
def search_articles():
    data = request.get_json()
    stock_ticker = data.get('stock_ticker')
    num_articles = int(data.get('num_articles', 5))
    start_date = data.get('start_date')

    if not stock_ticker or not start_date:
        return jsonify({'error': 'Stock ticker and start date are required'}), 400

    try:
        articles = fetch_articles(stock_ticker, num_articles, start_date)

        if not articles:
            return jsonify({'message': 'No articles found'}), 404

        if isinstance(articles, list) and len(articles) > 0 and 'error' in articles[0]:
            return jsonify({'error': articles[0]['error']}), 500

        logging.info(f"Returning {len(articles)} articles for {stock_ticker}")
        return jsonify({'articles': articles})

    except Exception as e:
        logging.error(f"Error in search_articles: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred'}), 500

@app.route('/analyze_article', methods=['POST'])
def analyze_article():
    data = request.get_json()
    article = data.get('article')
    stock_ticker = data.get('stock_ticker')

    if not article or not stock_ticker:
        return jsonify({'error': 'Article and stock ticker are required'}), 400

    try:
        analyzed_article = analyze_single_article(stock_ticker, article)
        return jsonify(analyzed_article)

    except Exception as e:
        logging.error(f"Error in analyze_article: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred'}), 500

@app.route('/generate_final_analysis', methods=['POST'])
def generate_final_analysis_route():
    data = request.get_json()
    articles = data.get('articles')

    if not articles:
        return jsonify({'error': 'Articles are required'}), 400

    try:
        final_analysis = generate_final_analysis(articles)
        return jsonify({'final_analysis': final_analysis})

    except Exception as e:
        logging.error(f"Error in generate_final_analysis: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred'}), 500

@app.route('/status', methods=['GET'])
def get_status():
    # Implement logic to return current status
    # This could be stored in a global variable or database
    return jsonify({'status': 'Current status message'})

def fetch_article_content(url):
    for attempt in range(MAX_RETRIES):
        try:
            # Explicitly disable proxies
            response = requests.get(url, headers=REQUEST_HEADERS, timeout=10, proxies={'http': None, 'https': None})
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            content_selectors = [
                'div.article-content', 'div.entry-content', 'article',
                'div.content', 'div.post-content'
            ]

            for selector in content_selectors:
                content_div = soup.select_one(selector)
                if content_div:
                    content = content_div.get_text(strip=True)
                    return content[:5000] if isinstance(content, str) else "Content not available"

            logging.warning(f"Content div not found for URL: {url}")
            return "Content not available"

        except requests.RequestException as e:
            logging.error(f"Attempt {attempt + 1} failed to fetch article content: {e}")
            logging.error(f"Request details: URL={url}, Headers={REQUEST_HEADERS}")
            if attempt == MAX_RETRIES - 1:
                return "Content not available"
            time.sleep(RETRY_DELAY)

def fetch_articles(stock_ticker, num_articles, start_date):
    url = f"https://finviz.com/quote.ashx?t={stock_ticker}"

    try:
        # Attempt to connect to finviz.com
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=10, proxies={'http': None, 'https': None})
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        news_table = soup.find('table', class_='news-table')

        if not news_table:
            logging.warning("No news table found in HTML")
            return []

        articles = []
        seen_titles = set()

        start_date = datetime.strptime(start_date, '%Y-%m-%d')

        for row in news_table.find_all('tr'):
            cols = row.find_all('td')
            if len(cols) < 2:
                continue

            title = cols[1].text.strip()
            link = cols[1].a['href'] if cols[1].a else None
            published_at = cols[0].text.strip()

            try:
                if len(published_at) > 8:  # Full date format
                    article_date = datetime.strptime(published_at, '%b-%d-%y %I:%M%p')
                else:  # Time only format (assume it's today)
                    article_date = datetime.combine(datetime.now().date(), datetime.strptime(published_at, '%I:%M%p').time())
            except ValueError:
                article_date = datetime.now()  # Use current date if parsing fails

            if article_date >= start_date and title and link and title not in seen_titles:
                seen_titles.add(title)
                full_link = f"https://finviz.com/{link}" if not link.startswith("http") else link
                articles.append({
                    'title': title,
                    'link': full_link,
                    'author': "Unknown",
                    'published_at': article_date.strftime('%Y-%m-%d %H:%M:%S'),
                })

                if len(articles) == num_articles:
                    break

        # Fetch content for selected articles
        with ThreadPoolExecutor() as executor:
            for article in articles:
                executor.submit(fetch_article_content, article['link'])

        return articles

    except requests.RequestException as e:
        logging.error(f"Failed to fetch articles from finviz: {e}")
        logging.error(f"Request details: URL={url}, Headers={REQUEST_HEADERS}")

        # Fallback to Yahoo Finance
        return fetch_articles_from_yahoo(stock_ticker, num_articles, start_date)

def fetch_articles_from_yahoo(stock_ticker, num_articles, start_date):
    try:
        ticker = yf.Ticker(stock_ticker)

        # Convert start_date to datetime object
        start_date = datetime.strptime(start_date, '%Y-%m-%d')

        # Fetch news for the past 30 days from the start date
        news = ticker.news

        filtered_news = [
            article for article in news
            if datetime.fromtimestamp(article['providerPublishTime']) >= start_date
        ]

        # If no articles found in the specified range, fetch the most recent articles
        if not filtered_news:
            logging.warning(f"No articles found for {stock_ticker} from {start_date}. Fetching most recent articles.")
            filtered_news = news[:num_articles]

        # Ensure we don't exceed the number of available articles
        num_articles = min(num_articles, len(filtered_news))

        formatted_articles = []
        for article in filtered_news[:num_articles]:
            content = fetch_article_content(article['link'])
            formatted_articles.append({
                'title': article['title'],
                'link': article['link'],
                'author': article.get('author', 'Unknown'),
                'published_at': datetime.fromtimestamp(article['providerPublishTime']).strftime('%Y-%m-%d %H:%M:%S'),
                'content': content if content else article.get('summary', 'Content not available')
            })

        logging.info(f"Fetched {len(formatted_articles)} articles for {stock_ticker}")
        return formatted_articles

    except Exception as e:
        logging.error(f"Failed to fetch articles from Yahoo Finance: {e}")
        return [{"error": f"Failed to fetch articles: {str(e)}"}]

def fetch_article_content(url):
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Try to find the main content of the article
        content_selectors = [
            'article', '.article-body', '.article-content', '.story-body',
            '[itemprop="articleBody"]', '.entry-content', '.post-content'
        ]

        for selector in content_selectors:
            content = soup.select_one(selector)
            if content:
                return content.get_text(strip=True)

        # If no content found, return None
        return None
    except Exception as e:
        logging.error(f"Error fetching article content: {e}")
        return None

def analyze_single_article(stock_ticker, article):
    logging.info(f"Analyzing article: {article['title']}")
    prompt = generate_analysis_prompt(article)

    try:
        response = model.generate_content(prompt)
        analysis_text = response.text.strip()

        one_month_projection = extract_projection(analysis_text, "1 Month")
        one_year_projection = extract_projection(analysis_text, "1 Year")

        analyzed_article = {
            'title': article['title'],
            'link': article['link'],
            'author': article['author'],
            'published_at': article['published_at'],
            'content': article['content'],
            'analysis': analysis_text,
            'estimated_returns_1_month': one_month_projection,
            'estimated_returns_1_year': one_year_projection
        }
        return analyzed_article
    except Exception as e:
        logging.error(f"Error occurred during article analysis: {e}")
        return {
            'title': article['title'],
            'link': article['link'],
            'author': article['author'],
            'published_at': article['published_at'],
            'content': article['content'],
            'analysis': 'Analysis failed',
            'estimated_returns_1_month': 'N/A',
            'estimated_returns_1_year': 'N/A'
        }

def extract_projection(analysis_text, time_frame):
    pattern = rf"Estimated Returns \({time_frame}\):\s*(.+?)(?:\n|$)"
    match = re.search(pattern, analysis_text)
    if match:
        return match.group(1).strip()
    return "Not available"

def generate_analysis_prompt(article):
    content = article['content'][:5000] if article['content'] else "Content not available"
    return f"""
    **Article Details:**
    Title: {article['title']}
    Published At: {article['published_at']}

    **Article Content:** {content}

    **Analysis:**
    1. **Strengths:** What are the key arguments or evidence presented in the article that support its main claims? Provide specific examples and quote relevant parts of the article.
    2. **Future Risk Assessment:** Based on the information in the article, what is the likelihood of the discussed issue or trend negatively impacting relevant stakeholders within the next year? Provide a percentage estimate (e.g., 30%) and a detailed justification based on the article's content.
    3. **Estimated Returns (1 Month):** Considering the article's content, what is the potential for positive outcomes or benefits to materialize within the next month? Provide a numerical estimate of the expected return or impact (e.g., +2.5%) and explain your reasoning, citing specific information from the article.
    4. **Estimated Returns (1 Year):** Considering the article's content, what is the potential for long-term positive outcomes or benefits to materialize within the next year? Provide a numerical estimate of the expected return or impact (e.g., +15%) and explain your reasoning, referencing relevant parts of the article.
    5. **Opportunities:** What potential opportunities for growth, innovation, or improvement are suggested or implied by the article? Elaborate on these opportunities and their potential impact, quoting or paraphrasing relevant sections of the article.
    6. **Threats:** What potential challenges, obstacles, or risks are identified or implied by the article? Describe these threats and their potential consequences, using specific information from the article to support your analysis.

    Please ensure that your analysis is thorough, specific to the article's content, and includes relevant quotes or paraphrases to support your points. Aim for a balanced analysis that considers both positive and negative aspects discussed in the article.
    """

def generate_final_analysis(articles):
    prompt = "**Final Summary Analysis:**\n\n"
    prompt += "Based on the following articles:\n\n"

    for article in articles:
        prompt += f"**Title:** {article['title']}\n**Content:** {article['content'][:500]}...\n\n"

    prompt += """
    Provide a comprehensive analysis covering the following aspects:

    1. **Overall Strengths and Weaknesses:**
       - **Strengths:**
         - [List positive aspects and achievements mentioned in the articles.]
       - **Weaknesses:**
         - [List limitations, challenges, or gaps.]

    2. **Likelihood of Negative Impacts and Risk Assessments:**
       - **Negative Impacts:**
         - [Identify and list potential negative effects mentioned in the articles.]
       - **Risk Assessment:**
         - [Evaluate and list the severity and probability of each risk.]

    3. **Expected Returns or Benefits:**
       - **Next Month:**
         - [Estimate returns or benefits in the next month based on trends or projections.]
       - **Next Year:**
         - [Project longer-term benefits or returns.]

    4. **Major Opportunities and Threats:**
       - **Opportunities:**
         - [Identify and list potential growth areas or advantages.]
       - **Threats:**
         - [Identify and list significant challenges or risks.]

    **Please format the analysis in Markdown for better readability:**
    - Use headings (## Heading) to organize sections.
    - Use bullet points (*) for lists.
    - Use bold (**) for key terms.
    - Only use articles related to the stock
    """

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logging.error(f"Error occurred while generating final analysis: {e}")
        return "Final analysis not available"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=False)

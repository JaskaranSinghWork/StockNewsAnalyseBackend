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

# Load environment variables and configure logging
load_dotenv()
logging.basicConfig(level=logging.INFO)

# Configure Google AI
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY not found in environment variables")
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-1.5-pro')

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Constants
MAX_RETRIES = 3
RETRY_DELAY = 2
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

@app.route('/search_articles', methods=['POST'])
def search_articles():
    data = request.get_json()
    stock_ticker = data.get('stock_ticker')
    num_articles = int(data.get('num_articles', 5))
    time_frame = int(data.get('time_frame', 7))
    
    if not stock_ticker:
        return jsonify({'error': 'Stock ticker is required'}), 400

    try:
        articles = fetch_articles(stock_ticker, num_articles, time_frame)
        if not articles:
            return jsonify({'message': 'No articles found'}), 404
        
        analyzed_articles = analyze_articles(stock_ticker, articles)
        final_analysis = generate_final_analysis(articles)
        response = {
            'final_analysis': final_analysis,
            'articles': analyzed_articles
        }
        return jsonify(response)
    
    except Exception as e:
        logging.error(f"Error in search_articles: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred'}), 500

def fetch_article_content(url):
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, headers=REQUEST_HEADERS, timeout=10)
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
            if attempt == MAX_RETRIES - 1:
                return "Content not available"
            time.sleep(RETRY_DELAY)

def fetch_articles(stock_ticker, num_articles, time_frame):
    url = f"https://finviz.com/quote.ashx?t={stock_ticker}"
    
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        news_table = soup.find('table', class_='news-table')
        
        if not news_table:
            logging.warning("No news table found in HTML")
            return []

        articles = []
        seen_titles = set()

        for row in news_table.find_all('tr'):
            cols = row.find_all('td')
            if len(cols) < 2:
                continue
            
            title = cols[1].text.strip()
            link = cols[1].a['href'] if cols[1].a else None
            published_at = cols[0].text.strip()

            if title and link and title not in seen_titles:
                seen_titles.add(title)
                full_link = f"https://finviz.com/{link}" if not link.startswith("http") else link
                content = fetch_article_content(full_link)
                articles.append({
                    'title': title,
                    'link': full_link,
                    'author': "Unknown",
                    'published_at': published_at,
                    'content': content
                })
            
            if len(articles) >= num_articles:
                break

        return articles

    except requests.RequestException as e:
        logging.error(f"Failed to fetch articles: {e}")
        raise RuntimeError(f"Failed to fetch articles: {str(e)}")

def analyze_articles(stock_ticker, articles):
    analyzed_articles = []
    seen_titles = set()

    for article in articles:
        if article['title'] in seen_titles:
            continue

        logging.info(f"Analyzing article: {article['title']}")
        prompt = generate_analysis_prompt(article)

        try:
            response = model.generate_content(prompt)
            analysis_text = response.text.strip()

            while len(analysis_text) < 1500:
                logging.info("Response too short. Fetching another article...")
                more_articles = fetch_articles(stock_ticker, 1, 7)
                if not more_articles:
                    logging.warning("No more articles to fetch.")
                    break
                new_article = more_articles[0]
                new_prompt = generate_analysis_prompt(new_article)
                response = model.generate_content(new_prompt)
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
            analyzed_articles.append(analyzed_article)
            seen_titles.add(article['title'])
        except Exception as e:
            logging.error(f"Error occurred during article analysis: {e}")
            analyzed_article = {
                'title': article['title'],
                'link': article['link'],
                'author': article['author'],
                'published_at': article['published_at'],
                'content': article['content'],
                'analysis': 'Analysis not available',
                'estimated_returns_1_month': 'Not available',
                'estimated_returns_1_year': 'Not available'
            }
            analyzed_articles.append(analyzed_article)

        time.sleep(1)

    return analyzed_articles

def extract_projection(analysis_text, time_frame):
    pattern = rf"Estimated Returns \({time_frame}\):\s*(.+?)(?:\n|$)"
    match = re.search(pattern, analysis_text)
    if match:
        return match.group(1).strip()
    return "Not available"

def generate_analysis_prompt(article):
    return f"""
    **Article Details:**
    Published At: {article['published_at']}

    **Article Content:** {article['content']}

    **Analysis:**
    1. **Strengths:** What are the key arguments or evidence presented in the article that support its main claims? Please provide specific examples.
    2. **Future Risk Assessment:** Based on the information in the article, what is the likelihood of the discussed issue or trend negatively impacting relevant stakeholders within the next year? Please provide a percentage estimate and detailed justification.
    3. **Estimated Returns (1 Month):** Considering the article's content, what is the potential for positive outcomes or benefits to materialize within the next month? Please provide a numerical estimate of the expected return or impact and explain your reasoning.
    4. **Estimated Returns (1 Year):** Considering the article's content, what is the potential for long-term positive outcomes or benefits to materialize within the next year? Please provide a numerical estimate of the expected return or impact and explain your reasoning.
    5. **Opportunities:** What potential opportunities for growth, innovation, or improvement are suggested or implied by the article? Please elaborate on these opportunities and their potential impact.
    6. **Threats:** What potential challenges, obstacles, or risks are identified or implied by the article? Please describe these threats and their potential consequences.
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
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logging.error(f"Error occurred while generating final analysis: {e}")
        return "Final analysis not available"

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=8080)
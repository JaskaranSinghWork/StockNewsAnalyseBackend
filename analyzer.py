from textblob import TextBlob
import pandas as pd
import yfinance as yf

def analyze_sentiment(article_text):
    analysis = TextBlob(article_text)
    return analysis.sentiment.polarity

def summarize_article(article_text):
    from gensim.summarization import summarize
    return summarize(article_text)

def get_stock_data(stock_symbol):
    stock = yf.Ticker(stock_symbol)
    return stock.history(period="1y")

def calculate_growth_potential(stock_data):
    stock_data['Moving Average'] = stock_data['Close'].rolling(window=30).mean()
    return stock_data

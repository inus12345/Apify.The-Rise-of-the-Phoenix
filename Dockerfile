FROM apify/actor-python-selenium:3.12

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY news_scraper ./news_scraper
COPY .actor ./.actor
COPY ACTOR.md ./

CMD ["python", "-m", "news_scraper.apify_actor"]

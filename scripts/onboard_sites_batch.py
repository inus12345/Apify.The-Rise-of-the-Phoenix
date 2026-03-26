"""Batch-onboard sites into the JSON catalog with live category discovery."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from news_scraper.config import (
    CategoryPaginationTracker,
    CategoryState,
    ScrapingTool,
    SelectorMap,
    SiteCatalog,
    ensure_utc,
    load_json_model,
    normalize_url,
    save_json_model,
    utc_now,
)
from news_scraper.scraping.engine import default_runtime_config


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
)
BAD_CATEGORY_PATH = re.compile(
    r"/(tag|tags|author|authors|search|login|subscribe|newsletter|privacy|terms|about|contact|advert|"
    r"video|videos|audio|podcast|live|shop|careers|jobs|events|epaper|cart|account|comment|comments|"
    r"user|register|password|faq|services|feed|cdn-cgi|email-protection|sabonner|offres|offers|checkout|"
    r"identity-service|helpcenter|media-kit|connexion|abonnement|abonnements|compte|journal|"
    r"avis-mortuaires|mentions-legales|a-propos|nous-contacter|web-tv|admin|users|newsletters|categories)"
    r"(/|$)",
    re.IGNORECASE,
)
BAD_CATEGORY_SUBSTRINGS = (
    "/redirect",
    "/consent",
    "/collectconsent",
    "/partners-list",
    "/v2/partners",
    "/post/submit",
    "/reader-resources",
    "/classifieds",
    "/help/",
    "/helpcenter",
)
BLOCK_INDICATORS = (
    "bot verification",
    "verify you are human",
    "access denied",
    "too many requests",
    "captcha",
    "account suspended",
    "suspended account",
    "this account has been suspended",
)
BAD_CATEGORY_TEXT = re.compile(
    r"\b(login|connexion|connecter|contact|about|a propos|mentions|legal|privacy|terms|"
    r"abonnement|subscribe|newsletter|epaper|account|compte|journal|web[-\s]?tv|admin)\b",
    re.IGNORECASE,
)
CATEGORY_HINTS = re.compile(
    r"(actualite|actualites|actu|news|rubrique|category|categorie|section|topic|"
    r"politique|economie|business|sport|sports|societe|culture|opinion|international|"
    r"nation|monde|world|local|afrique|africa|sante|health)",
    re.IGNORECASE,
)
LANGUAGE_OVERRIDES = {
    "Al-Masry Al-Youm (The Egyptian Today)": "ar",
    "Benin WebTV": "fr",
}
BASE_URL_OVERRIDES = {
    "malikunafoni": "https://malikunafoni.com/",
    "Mpumalanga News": "https://www.citizen.co.za/mpumalanga-news/",
    "Northern Natal News": "https://www.citizen.co.za/northern-natal-news/local/news-headlines/",
    "Okay NG": "https://www.okaynews.com/",
    "Pacific Islands Report": "https://www.eastwestcenter.org/pidp",
    "Paul Kagame": "https://www.paulkagame.rw/",
    "Politiko": "https://visayas.politiko.com.ph/",
    "Pulse Live": "https://www.pulse.co.ke/",
    "SAM": "https://sam.gov/opp",
    "Solomon Times": "https://www.solomontimes.com/",
    "South African Jewish Report": "https://www.sajr.co.za/category/religion/",
    "South Coast Sun": "https://www.citizen.co.za/south-coast-sun/local/news-headlines/",
    "South Sudan News Agency": "https://ssnanews.com/index_php/health/",
    "Southlands Sun": "https://www.citizen.co.za/southlands-sun/local/news-headlines/",
    "Thai PBS": "https://world.thaipbs.or.th/",
    "The Edge Markets": "https://theedgemarkets.com/options/digitaledge",
    "The Herald Zimbabwe": "https://www.heraldonline.co.zw/",
    "The Sun VoTN": "https://thesun.ng/",
    "TODAY": "https://todayonline.com/latest-news",
    "USTDA": "https://www.ustda.gov/news/",
    "VOA": "https://www.voaportugues.com/africa-e-mundo",
}
FORCE_INACTIVE_SITE_REASONS = {
    "Mozambique Insights": "Homepage currently yields no extractable article links, so scraping is disabled until the site structure changes.",
    "Mocambique Para Todos": "Domain currently redirects to a parked/holding page, so scraping is disabled.",
    "Noticias de Defesa": "Homepage appears to be a static/government-style bulletin page without extractable article body/date fields for this scraper schema.",
    "Palawan News": "Homepage consistently returns HTTP 403 to this scraper stack, so scraping is disabled until access restrictions are relaxed.",
    "Politico": "Primary domain currently times out from this runtime environment, so scraping is disabled until connectivity stabilizes.",
    "Propaganda Media Agency": "Domain currently serves a suspended account page, so scraping is disabled.",
    "Radio Maria Rwanda": "Homepage consistently returns HTTP 403 to this scraper stack, so scraping is disabled until access restrictions are relaxed.",
    "Radio One": "Domain is currently unreachable from this runtime environment (connection errors), so scraping is disabled.",
    "Radio Star Bukavu": "Current article pages do not expose required title/body/date fields for this scraper schema, so scraping is disabled until selectors are reworked.",
    "Radyo Bandera": "Domain is currently unreachable from this runtime environment (connection errors), so scraping is disabled.",
    "Rainforest": "Site is a recruitment board and does not expose article-style content compatible with this scraper schema.",
    "Reuters": "Homepage currently returns HTTP 401/forbidden to this scraper stack, so scraping is disabled until access restrictions are relaxed.",
    "Satenaw News": "Domain currently redirects to a different publication domain, so scraping is disabled to avoid collecting from the wrong source.",
    "Semonegna": "Domain currently presents an SSL certificate hostname mismatch, so scraping is disabled until certificate configuration is fixed.",
    "Seychelles News Agency": "Homepage currently returns HTTP 403 to this scraper stack, so scraping is disabled until access restrictions are relaxed.",
    "Seychelles news agency": "Homepage currently returns HTTP 403 to this scraper stack, so scraping is disabled until access restrictions are relaxed.",
    "Seychelles The Independent": "Domain is currently unresolved/unreachable from this runtime environment, so scraping is disabled.",
    "South African Jewish Report": "Current listing pages do not consistently expose extractable article links with this scraper stack, so scraping is disabled until selectors are reworked.",
    "Sudan Plus": "Domain currently appears repurposed for non-news content and does not provide compatible article pages for this scraper schema.",
    "Sudan Tribune English": "Homepage currently returns HTTP 403 to this scraper stack, so scraping is disabled until access restrictions are relaxed.",
    "Taarifa English": "Primary domain is currently refusing connections from this runtime environment, so scraping is disabled until connectivity is restored.",
    "Talamua": "Homepage currently times out from this runtime environment, so scraping is disabled until connectivity stabilizes.",
    "talent-to-market": "Domain is currently unresolved/unreachable from this runtime environment, so scraping is disabled.",
    "Techno Africa": "Domain is currently unresolved/unreachable from this runtime environment, so scraping is disabled.",
    "Thai PBS": "Current pages render as JS-app shells without crawlable article links in this scraper stack, so scraping is disabled until parser support is expanded.",
    "Tempo": "Homepage currently returns HTTP 403 to this scraper stack, so scraping is disabled until access restrictions are relaxed.",
    "Tempo Timor": "Domain currently serves a suspended/holding page rather than article content, so scraping is disabled.",
    "Tesfa News .com": "Domain is currently unresolved/unreachable from this runtime environment, so scraping is disabled.",
    "Tesfa News .net": "Domain currently does not expose extractable article listings compatible with this scraper schema.",
    "The Arabian Marketer": "Domain currently refuses connections from this runtime environment, so scraping is disabled.",
    "The Edge Markets": "Current listing pages expose utility/navigation links but no stable article pages with required extractable fields in this scraper schema.",
    "The Manila Times": "Homepage currently returns HTTP 403 to this scraper stack, so scraping is disabled until access restrictions are relaxed.",
    "The Print": "Homepage currently cannot be reached from this runtime environment, so scraping is disabled.",
    "The Quest Times": "Domain currently redirects to an unrelated non-news page, so scraping is disabled.",
    "The Rwandan": "Domain currently has an expired SSL certificate, so scraping is disabled until certificate issues are fixed.",
    "Tuoi Tre News": "Homepage currently presents bot-protection/access-check behavior, so scraping is disabled until access restrictions are relaxed.",
    "Vetogate": "Category/listing routes currently return HTTP 403 or anti-bot responses in this runtime, so scraping is disabled until access restrictions are relaxed.",
    "Wal Fadjri L'Aurore": "Homepage currently returns access-blocked responses across available scraping tools, so scraping is disabled until access restrictions are relaxed.",
    "Wataninet": "Homepage currently returns access-blocked responses across available scraping tools, so scraping is disabled until access restrictions are relaxed.",
    "Wataninet English": "Homepage currently returns access-blocked responses across available scraping tools, so scraping is disabled until access restrictions are relaxed.",
    "ZBC news": "Homepage currently returns access-blocked responses across available scraping tools, so scraping is disabled until access restrictions are relaxed.",
    "Zurich 24": "Domain is currently unreachable/intermittently unreachable from this runtime environment, so scraping is disabled until connectivity stabilizes.",
    "Zoom Tchad": "Homepage currently does not expose article-style listings compatible with this scraper schema.",
}
CATEGORY_OVERRIDES: dict[str, list[str]] = {
    "Al-Masry Al-Youm (The Egyptian Today)": [
        "https://www.almasryalyoum.com/section/index/3",
        "https://www.almasryalyoum.com/section/index/2",
        "https://www.almasryalyoum.com/section/index/8",
        "https://www.almasryalyoum.com/section/index/7",
        "https://www.almasryalyoum.com/section/index/4",
        "https://www.almasryalyoum.com/section/index/126",
    ],
    "Adiac - Congo": [
        "https://www.adiac-congo.com/rubrique/sport",
        "https://www.adiac-congo.com/rubrique/societe",
        "https://www.adiac-congo.com/rubrique/enquetes",
        "https://www.adiac-congo.com/rubrique/economie",
        "https://www.adiac-congo.com/rubrique/environnement",
        "https://www.adiac-congo.com/rubrique/politique",
    ],
    "Agefi": [
        "https://agefi.com/actualites/entreprises",
        "https://agefi.com/actualites/marches",
        "https://agefi.com/actualites/politique",
    ],
    "Alarab": [
        "https://alarab.qa/category/%D9%85%D8%AD%D9%84%D9%8A%D8%A7%D8%AA",
        "https://alarab.qa/category/%D8%A7%D9%84%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1-%D8%A7%D9%84%D8%B9%D8%A7%D9%85%D8%A9",
        "https://alarab.qa/category/%D8%A7%D9%84%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1-%D8%A7%D9%84%D8%B1%D8%B3%D9%85%D9%8A%D8%A9",
        "https://alarab.qa/category/%D8%AA%D8%AD%D9%82%D9%8A%D9%82%D8%A7%D8%AA",
        "https://alarab.qa/category/%D8%A7%D9%82%D8%AA%D8%B5%D8%A7%D8%AF",
        "https://alarab.qa/category/%D8%B1%D9%8A%D8%A7%D8%B6%D8%A9",
    ],
    "Algerie Eco": [],
    "Agence d'Information du Burkina": [
        "https://www.aib.media/regions",
        "https://www.aib.media/evenements",
    ],
    "All Africa": [],
    "All Africa Fr": [],
    "Allgemeine Zeitung": [
        "https://www.az.com.na/sport",
        "https://www.az.com.na/gesundheit",
        "https://www.az.com.na/tourismus",
        "https://www.az.com.na/politik",
        "https://www.az.com.na/market-watch",
        "https://www.az.com.na/focus",
    ],
    "Akhbar Libya 24": [
        "https://akhbarlibya24.net/%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1-%D9%84%D9%8A%D8%A8%D9%8A%D8%A7",
        "https://akhbarlibya24.net/category/%D8%B9%D9%8A%D9%86-%D8%B9%D9%84%D9%89-%D8%A7%D9%84%D8%AC%D9%86%D9%88%D8%A8",
        "https://akhbarlibya24.net/category/%D8%AC%D8%B1%D8%A7%D8%A6%D9%85-%D8%A7%D9%84%D9%85%D8%AC%D8%AA%D9%85%D8%B9",
        "https://akhbarlibya24.net/category/%D8%AA%D9%82%D8%A7%D8%B1%D9%8A%D8%B1",
        "https://akhbarlibya24.net/category/%D8%AC%D8%B1%D8%A7%D8%A6%D9%85-%D8%A7%D9%84%D8%A7%D8%B1%D9%87%D8%A7%D8%A8",
        "https://akhbarlibya24.net/category/%D8%A7%D9%84%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1/%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1_%D8%AF%D9%88%D9%84%D9%8A%D8%A9",
    ],
    "Al Sudani": [
        "https://alsudaninews.com/?cat=1",
        "https://alsudaninews.com/?cat=84",
        "https://alsudaninews.com/?cat=6",
        "https://alsudaninews.com/?cat=2",
        "https://alsudaninews.com/?cat=3",
        "https://alsudaninews.com/?cat=7",
    ],
    "Al Tagyheer": [
        "https://www.altaghyeer.info/ar/category/news",
        "https://www.altaghyeer.info/ar/category/columns_articles",
        "https://www.altaghyeer.info/ar/category/investigative_reports",
        "https://www.altaghyeer.info/ar/category/interviews",
        "https://www.altaghyeer.info/ar/category/sport-ar",
        "https://www.altaghyeer.info/ar/category/international-news",
    ],
    "Assayha": [
        "https://www.assayha.net/category/%D8%A7%D9%84%D8%A7%D8%AE%D8%A8%D8%A7%D8%B1",
        "https://www.assayha.net/category/%D8%A7%D9%84%D8%AA%D8%AD%D9%82%D9%8A%D9%82%D8%A7%D8%AA",
        "https://www.assayha.net/category/%D8%A7%D9%84%D8%AD%D9%88%D8%A7%D8%B1%D8%A7%D8%AA",
        "https://www.assayha.net/category/%D8%A7%D9%84%D8%A7%D9%82%D8%AA%D8%B5%D8%A7%D8%AF",
        "https://www.assayha.net/category/%D8%A7%D9%84%D9%88%D9%84%D8%A7%D9%8A%D8%A7%D8%AA",
        "https://www.assayha.net/category/%D8%A7%D9%84%D8%B1%D9%8A%D8%A7%D8%B6%D8%A9",
    ],
    "Aujord'hui au Faso": [
        "https://www.aujourd8.net/category/news-du-jour",
        "https://www.aujourd8.net/category/news-du-vsd",
        "https://www.aujourd8.net/category/politique",
        "https://www.aujourd8.net/category/cooperation",
        "https://www.aujourd8.net/category/developpement",
        "https://www.aujourd8.net/category/societe",
    ],
    "Benin WebTV": [
        "https://beninwebtv.com/pays/afrique/afrique-de-louest/benin/",
        "https://beninwebtv.com/news/",
        "https://beninwebtv.com/people/",
        "https://beninwebtv.com/sport/",
        "https://beninwebtv.com/elle/",
        "https://beninwebtv.com/communiques/",
    ],
    "BizNews.com": [],
    "Bloemfontein Courant": [],
    "Bombo Radyo Philippines": [],
    "Borkena AM": [],
    "Borkena EN": [
        "https://borkena.com/ethiopian-news-today/world-news/",
    ],
    "Bulgar": [],
    "Business Live": [
        "https://www.businessday.co.za/news",
        "https://www.businessday.co.za/politics",
        "https://www.businessday.co.za/opinion",
        "https://www.businessday.co.za/companies",
        "https://www.businessday.co.za/world",
        "https://www.businessday.co.za/markets",
    ],
    "Business News": [],
    "Business Today ME": [],
    "alakhbar": [
        "https://www.alakhbar.info/latest",
        "https://www.alakhbar.info/tag/akhbar",
        "https://www.alakhbar.info/tag/tahqiqat",
        "https://www.alakhbar.info/tag/mqabelat",
        "https://www.alakhbar.info/tag/international",
        "https://www.alakhbar.info/tag/opinions",
    ],
    "Cabo Ligado": [
        "https://caboligado.com/reports",
        "https://caboligado.com/update",
    ],
    "CAERT": [
        "https://caert.org.dz/auc-communiques-2",
        "https://caert.org.dz/reports",
        "https://caert.org.dz/analysis",
        "https://caert.org.dz/research-papers",
    ],
    "Capital FM": [
        "https://www.capitalfm.co.ke/news",
        "https://www.capitalfm.co.ke/business",
        "https://www.capitalfm.co.ke/sports",
    ],
    "Caprivi Vision": [
        "https://www.caprivivision.com/news",
        "https://www.caprivivision.com/category/editorial",
        "https://www.caprivivision.com/category/letters",
    ],
    "Carta de Mozambique": [
        "https://cartamz.com/carta-da-semana",
        "https://cartamz.com/politica",
    ],
    "Centro de Integridade Publica": [
        "https://www.cipmoz.org/historias-de-vida",
    ],
    "Centro para a Democracia e Desenvolvimento": [
        "https://cddmoz.org/blog",
    ],
    "Channel NewsAsia": [
        "https://www.channelnewsasia.com/asia",
        "https://www.channelnewsasia.com/world",
        "https://www.channelnewsasia.com/singapore",
        "https://www.channelnewsasia.com/business",
    ],
    "China Press": [],
    "Citizen Digital": [
        "https://citizen.digital/news",
        "https://citizen.digital/business",
        "https://citizen.digital/sports",
    ],
    "Connection Ivoirienne": [
        "https://connectionivoirienne.net/on-dit-quoi-au-pays",
        "https://connectionivoirienne.net/sante",
        "https://connectionivoirienne.net/intelligences",
        "https://connectionivoirienne.net/politique",
        "https://connectionivoirienne.net/libre-opinion",
        "https://connectionivoirienne.net/economie",
        "https://connectionivoirienne.net/monde-afrique",
    ],
    "Congo Nouveau": [
        "https://congonouveau.org/category/actualite",
        "https://congonouveau.org/category/politique",
        "https://congonouveau.org/category/opinion",
        "https://congonouveau.org/category/nation",
        "https://congonouveau.org/category/justice",
    ],
    "Daily Tribune": [
        "https://tribune.net.ph/news",
        "https://tribune.net.ph/news/nation",
        "https://tribune.net.ph/news/world",
        "https://tribune.net.ph/business",
        "https://tribune.net.ph/sports",
        "https://tribune.net.ph/commentary/opinion",
    ],
    "Daily Trust": [
        "https://dailytrust.com/topics/news",
        "https://dailytrust.com/topics/business",
        "https://dailytrust.com/topics/politics",
        "https://dailytrust.com/topics/sports",
        "https://dailytrust.com/topics/international",
    ],
    "DailyPost (Vanuatu)": [
        "https://www.dailypost.vu/news",
        "https://www.dailypost.vu/news/local_news/",
        "https://www.dailypost.vu/chinese_news/",
    ],
    "DFA": [
        "https://dfa.co.za/news/",
        "https://dfa.co.za/sport/",
        "https://dfa.co.za/opinion/",
    ],
    "Dayniile": [
        "https://www.dayniiile.com/category/technews/",
        "https://www.dayniiile.com/category/software/",
        "https://www.dayniiile.com/category/digital/",
        "https://www.dayniiile.com/category/smartphone/",
    ],
    "Der Brienzer": [],
    "Die Republikein": [],
    "Doha News": [
        "https://dohanews.co/category/news",
        "https://dohanews.co/category/sports",
        "https://dohanews.co/category/life",
        "https://dohanews.co/category/science-technology",
    ],
    "Dubai 92": [
        "https://www.dubai92.com/news/",
    ],
    "Dubai Eye 103.8": [
        "https://www.dubaieye1038.com/news/",
        "https://www.dubaieye1038.com/news/local/",
        "https://www.dubaieye1038.com/news/international/",
        "https://www.dubaieye1038.com/news/business/",
        "https://www.dubaieye1038.com/news/sports/",
        "https://www.dubaieye1038.com/news/entertainment/",
    ],
    "Dubai Week": [
        "https://www.dubaiweek.ae/news/",
        "https://www.dubaiweek.ae/business/",
        "https://www.dubaiweek.ae/lifestyle/",
        "https://www.dubaiweek.ae/sport/",
        "https://www.dubaiweek.ae/tech/",
        "https://www.dubaiweek.ae/travel/",
        "https://www.dubaiweek.ae/real-estate/",
    ],
    "Detik.com Inet": [
        "https://inet.detik.com/gadget",
        "https://inet.detik.com/games",
        "https://inet.detik.com/business-policy",
        "https://inet.detik.com/science",
    ],
    "Detik.com News": [
        "https://news.detik.com/berita",
        "https://news.detik.com/jabodetabek",
        "https://news.detik.com/internasional",
        "https://news.detik.com/hukum",
    ],
    "Eagle News": [
        "https://www.eaglenews.ph/category/national",
        "https://www.eaglenews.ph/category/metro",
        "https://www.eaglenews.ph/category/province",
        "https://www.eaglenews.ph/category/province/luzon",
        "https://www.eaglenews.ph/category/province/visayas",
        "https://www.eaglenews.ph/category/province/mindanao",
        "https://www.eaglenews.ph/category/interviews",
    ],
    "Emirates News Wire": [
        "https://emiratesnewswire.ae/category/general/",
        "https://emiratesnewswire.ae/category/education/",
        "https://emiratesnewswire.ae/category/arts-culture/",
        "https://emiratesnewswire.ae/category/health-safety/",
        "https://emiratesnewswire.ae/category/internal-affairs/",
        "https://emiratesnewswire.ae/category/athletic/",
        "https://emiratesnewswire.ae/category/press-release/",
    ],
    "Ethiopia Insight": [
        "https://www.ethiopia-insight.com/ethiopia-insight/",
        "https://www.ethiopia-insight.com/category/newsanalysis/",
        "https://www.ethiopia-insight.com/category/indepth/",
        "https://www.ethiopia-insight.com/category/viewpoint/",
        "https://www.ethiopia-insight.com/category/insights/",
        "https://www.ethiopia-insight.com/news-costs/",
    ],
    "Mocambique Para Todos": [],
    "malikunafoni": [
        "https://malikunafoni.com/category/actualites",
        "https://malikunafoni.com/category/culture",
        "https://malikunafoni.com/category/international",
        "https://malikunafoni.com/category/politique",
        "https://malikunafoni.com/category/sports",
        "https://malikunafoni.com/category/faitsdivers",
    ],
    "March Anzeiger": [
        "https://www.marchanzeiger.ch/category/sport/ep-sport",
        "https://www.marchanzeiger.ch/category/aktuelles",
        "https://www.marchanzeiger.ch/category/politik",
        "https://www.marchanzeiger.ch/category/region",
        "https://www.marchanzeiger.ch/category/wirtschaft",
    ],
    "MBC Radio": [
        "https://mbcradio.tv/news",
        "https://mbcradio.tv/news/sports",
        "https://mbcradio.tv/replay/news",
        "https://mbcradio.tv/mbc-1",
        "https://mbcradio.tv/node",
    ],
    "mmegi": [
        "https://www.mmegi.bw/business",
        "https://www.mmegi.bw/news",
        "https://www.mmegi.bw/sports",
        "https://www.mmegi.bw/world",
        "https://www.mmegi.bw/opinion-analysis",
        "https://www.mmegi.bw/blogs",
    ],
    "Mpumalanga Mirror": [
        "https://mpmirroronline.co.za/category/local-news",
        "https://mpmirroronline.co.za/category/sports",
        "https://mpmirroronline.co.za/category/crime",
        "https://mpmirroronline.co.za/category/education",
        "https://mpmirroronline.co.za/category/entertainment",
        "https://mpmirroronline.co.za/category/politics",
        "https://mpmirroronline.co.za/category/tourism",
    ],
    "Mpumalanga News": [
        "https://www.citizen.co.za/mpumalanga-news/",
        "https://www.citizen.co.za/mpumalanga-news/national-news",
        "https://www.citizen.co.za/mpumalanga-news/network-sport",
        "https://www.citizen.co.za/mpumalanga-news/local/news-headlines",
        "https://www.citizen.co.za/mpumalanga-news/local/news-headlines/business",
        "https://www.citizen.co.za/mpumalanga-news/local/news-headlines/local-news",
        "https://www.citizen.co.za/mpumalanga-news/local/sports-news",
    ],
    "Myjoy online": [
        "https://www.myjoyonline.com/news",
        "https://www.myjoyonline.com/sports",
    ],
    "MZN News": [
        "https://mznews.co.mz/actualidade",
        "https://mznews.co.mz/desporto",
        "https://mznews.co.mz/agricultura",
        "https://mznews.co.mz/carreiras",
        "https://mznews.co.mz/economia",
        "https://mznews.co.mz/empresas",
        "https://mznews.co.mz/imobiliario",
    ],
    "MyBroadband Companies": [
        "https://companies.mybroadband.co.za/hostafrica",
        "https://companies.mybroadband.co.za/linkafrica",
        "https://companies.mybroadband.co.za/paratus-africa",
        "https://companies.mybroadband.co.za/bbd",
        "https://companies.mybroadband.co.za/celerity",
    ],
    "Mozambique Insights": [],
    "NewsKo": [
        "https://newsko.com.ph/category/news-national/",
        "https://newsko.com.ph/category/crimes/",
        "https://newsko.com.ph/category/showbiz/",
        "https://newsko.com.ph/category/sports/",
        "https://newsko.com.ph/category/media-movers/",
        "https://newsko.com.ph/category/opinyon/",
        "https://newsko.com.ph/category/brand-news/",
    ],
    "Newsmoris": [],
    "Niger Inter": [
        "https://nigerinter.com/category/actu/",
        "https://nigerinter.com/category/culture/",
        "https://nigerinter.com/category/culture-et-sport/",
        "https://nigerinter.com/category/economie/",
        "https://nigerinter.com/category/international/",
        "https://nigerinter.com/category/opinions/",
        "https://nigerinter.com/category/societe/",
    ],
    "Northern Natal News": [
        "https://www.citizen.co.za/northern-natal-news/local/news-headlines/",
        "https://www.citizen.co.za/northern-natal-news/local/news-headlines/local-news/",
        "https://www.citizen.co.za/northern-natal-news/local/news-headlines/local-crime-news/",
        "https://www.citizen.co.za/northern-natal-news/local/news-headlines/local-municipal-news/",
        "https://www.citizen.co.za/northern-natal-news/local/news-headlines/local-school-news/",
        "https://www.citizen.co.za/northern-natal-news/local/news-headlines/business/",
        "https://www.citizen.co.za/northern-natal-news/local/sports-news/",
    ],
    "Noticias de Defesa": [],
    "Okay NG": [
        "https://www.okaynews.com/news/",
        "https://www.okaynews.com/politics/",
        "https://www.okaynews.com/business-news/",
        "https://www.okaynews.com/technology/",
        "https://www.okaynews.com/security/",
        "https://www.okaynews.com/entertainment-news/",
        "https://www.okaynews.com/sports/",
    ],
    "Pacific Community": [
        "https://spc.int/updates/news",
        "https://spc.int/updates/blog",
    ],
    "Pacific Islands Report": [
        "https://www.eastwestcenter.org/pidp",
        "https://www.eastwestcenter.org/news",
    ],
    "Paul Kagame": [
        "https://www.paulkagame.rw/news/",
        "https://www.paulkagame.rw/speeches/",
    ],
    "Pinoy Weekly": [
        "https://pinoyweekly.org/category/balita",
        "https://pinoyweekly.org/category/kultura",
        "https://pinoyweekly.org/category/lathalain",
        "https://pinoyweekly.org/category/multimedia",
    ],
    "Politiko": [
        "https://bicol.politiko.com.ph/",
        "https://centralluzon.politiko.com.ph/",
        "https://metromanila.politiko.com.ph/",
        "https://mindanao.politiko.com.ph/",
        "https://southluzon.politiko.com.ph/",
        "https://visayas.politiko.com.ph/",
    ],
    "Premium Times": [
        "https://www.premiumtimesng.com/news/headlines",
        "https://www.premiumtimesng.com/category/business",
        "https://www.premiumtimesng.com/category/politics",
        "https://www.premiumtimesng.com/category/health",
    ],
    "Pulse Live": [
        "https://www.pulse.co.ke/news",
        "https://www.pulse.co.ke/local",
        "https://www.pulse.co.ke/business",
        "https://www.pulse.co.ke/entertainment",
    ],
    "SAM": [
        "https://sam.gov/opp",
    ],
    "Sierra Express Media": [
        "https://sierraexpressmedia.com/category/african-affairs",
        "https://sierraexpressmedia.com/category/culture-life",
        "https://sierraexpressmedia.com/category/national-news",
        "https://sierraexpressmedia.com/category/opinion-desk",
        "https://sierraexpressmedia.com/category/development-watch",
    ],
    "Solomon Times": [
        "https://www.solomontimes.com/news/latest",
    ],
    "South African Jewish Report": [
        "https://www.sajr.co.za/category/religion/",
    ],
    "South Coast Sun": [
        "https://www.citizen.co.za/south-coast-sun/local/news-headlines/",
    ],
    "South Sudan News Agency": [
        "https://ssnanews.com/index_php/health/",
        "https://ssnanews.com/index_php/world/",
        "https://ssnanews.com/index_php/education/",
        "https://ssnanews.com/index_php/travel/",
    ],
    "South Sudan News Now": [
        "https://ssnewsnow.com/world",
        "https://ssnewsnow.com/newsbeat/press-releases",
        "https://ssnewsnow.com/world/south-sudan",
    ],
    "Southlands Sun": [
        "https://www.citizen.co.za/southlands-sun/local/news-headlines/",
    ],
    "Sunday Punch": [
        "https://punch.dagupan.com/category/business",
        "https://punch.dagupan.com/category/opinion",
        "https://punch.dagupan.com/category/sports",
        "https://punch.dagupan.com/last-weeks-news",
        "https://punch.dagupan.com/category/news/inside-news",
        "https://punch.dagupan.com/category/opinion/newsy-news",
        "https://punch.dagupan.com/category/governance",
    ],
    "Sunday World": [
        "https://sundayworld.co.za/category/business",
        "https://sundayworld.co.za/category/news",
        "https://sundayworld.co.za/category/sports",
        "https://sundayworld.co.za/category/lifestyle",
        "https://sundayworld.co.za/category/politics",
        "https://sundayworld.co.za/category/news/fashion",
        "https://sundayworld.co.za/category/news/gadgets",
    ],
    "Swaziland News": [
        "http://swazilandnews.co.za/index.php",
    ],
    "Talk of Juba": [
        "https://www.talkofjuba.com/news",
        "https://www.talkofjuba.com/opinion",
        "https://www.talkofjuba.com/sport",
        "https://www.talkofjuba.com/entertainment",
        "https://www.talkofjuba.com/life",
    ],
    "Tech Central": [
        "https://techcentral.co.za/category/news",
        "https://techcentral.co.za/category/opinion",
        "https://techcentral.co.za/category/sections",
        "https://techcentral.co.za/category/world",
    ],
    "Thai PBS": [
        "https://world.thaipbs.or.th/category/news/",
        "https://world.thaipbs.or.th/category/thailand/",
    ],
    "Thairath": [
        "https://www.thairath.co.th/news",
        "https://www.thairath.co.th/newspaper",
        "https://www.thairath.co.th/entertain",
        "https://www.thairath.co.th/home",
        "https://www.thairath.co.th/horoscope",
        "https://www.thairath.co.th/lifestyle",
        "https://www.thairath.co.th/lottery",
    ],
    "The Cable": [],
    "The Cable Lifestyle": [],
    "The Edge Markets": [
        "https://theedgemarkets.com/options/digitaledge",
        "https://theedgemarkets.com/options/esg",
    ],
    "The Guardian Nigeria": [
        "https://guardian.ng/category/business-services",
        "https://guardian.ng/category/news",
        "https://guardian.ng/category/opinion",
        "https://guardian.ng/category/sport",
        "https://guardian.ng/category/business-services/agro-care",
        "https://guardian.ng/category/business-services/business",
    ],
    "The Herald Zimbabwe": [],
    "The Jet Newspaper": [
        "http://www.thejetnewspaper.com/category/business",
        "http://www.thejetnewspaper.com/category/news",
        "http://www.thejetnewspaper.com/category/sports",
        "http://www.thejetnewspaper.com/category/life-style/health",
        "http://www.thejetnewspaper.com/category/news/world",
        "http://www.thejetnewspaper.com/category/education",
        "http://www.thejetnewspaper.com/category/government",
    ],
    "The Local": [
        "https://www.thelocal.ch/category/switzerland-news",
    ],
    "The Newspaper": [],
    "The Peninsula": [
        "https://islamonline.net/category/books",
        "https://islamonline.net/category/feker",
    ],
    "The Point": [
        "https://thepoint.gm/arts-and-culture",
        "https://thepoint.gm/health",
        "https://thepoint.gm/africa/gambia/national-news",
        "https://thepoint.gm/africa/gambia/opinion",
        "https://thepoint.gm/africa/gambia/sports",
        "https://thepoint.gm/africa/gambia/article",
        "https://thepoint.gm/africa/gambia/feature",
    ],
    "The Sierra Leone Telegraph": [
        "https://www.thesierraleonetelegraph.com/category/sports",
        "https://www.thesierraleonetelegraph.com/category/election-watch",
        "https://www.thesierraleonetelegraph.com/category/in-focus",
        "https://www.thesierraleonetelegraph.com/category/politics-and-law",
    ],
    "The Star Malaysia": [
        "https://www.thestar.com.my/business",
        "https://www.thestar.com.my/education/news",
        "https://www.thestar.com.my/lifestyle/health-and-family",
        "https://www.thestar.com.my/lifestyle/travel-and-culture",
        "https://www.thestar.com.my/metro/community-sports",
        "https://www.thestar.com.my/metro/metro-news",
        "https://www.thestar.com.my/news",
    ],
    "The Sun VoTN": [
        "https://thesun.ng/category/news/",
        "https://thesun.ng/category/politics/",
    ],
    "Uganda Media Centre": [
        "https://mediacentre.go.ug/latest-news.php",
        "https://mediacentre.go.ug/opinions.php",
        "https://mediacentre.go.ug/articles.php",
        "https://mediacentre.go.ug/publications.php",
    ],
    "USTDA": [
        "https://www.ustda.gov/news/",
    ],
    "Verdade": [
        "https://verdade.co.mz/category/desporto",
        "https://verdade.co.mz/category/newsflash",
        "https://verdade.co.mz/category/ambiente",
        "https://verdade.co.mz/category/democracia",
        "https://verdade.co.mz/category/economia",
        "https://verdade.co.mz/category/nacional",
        "https://verdade.co.mz/category/opiniao",
        "https://verdade.co.mz/category/saude-e-bem-estar",
    ],
    "Vetogate": [],
    "VOA": [
        "https://www.voaportugues.com/africa-e-mundo",
        "https://www.voaportugues.com/voa60-africa",
        "https://www.voaportugues.com/z/7279",
        "https://www.voaportugues.com/angola",
        "https://www.voaportugues.com/brasil",
        "https://www.voaportugues.com/dossiers-especiais",
    ],
    "Voice of Nigeria Arabic": [
        "https://french.von.gov.ng/category/afrique",
        "https://french.von.gov.ng/category/economie",
        "https://french.von.gov.ng/category/monde",
        "https://french.von.gov.ng/category/sports",
        "https://french.von.gov.ng/category/nigeria",
    ],
    "Voice of Nigeria French": [
        "https://arabic.von.gov.ng/category/africa",
        "https://arabic.von.gov.ng/category/nigeria",
        "https://arabic.von.gov.ng/category/politics",
        "https://arabic.von.gov.ng/category/world",
    ],
    "Voice of the Cape": [
        "https://vocfm.co.za/news",
        "https://vocfm.co.za/category/news/local",
        "https://vocfm.co.za/category/international-news",
        "https://vocfm.co.za/category/opinions",
        "https://vocfm.co.za/category/sports-news",
    ],
    "Watson": [
        "https://www.watson.ch/international",
        "https://www.watson.ch/sport",
        "https://www.watson.ch/wintersport",
        "https://www.watson.ch/cute-news",
        "https://www.watson.ch/gute-news",
    ],
    "Windhoek Observer": [
        "https://www.observer24.com.na/category/latest-news",
        "https://www.observer24.com.na/category/national",
        "https://www.observer24.com.na/category/opinions",
        "https://www.observer24.com.na/category/sports",
        "https://www.observer24.com.na/category/observer-money",
        "https://www.observer24.com.na/category/energy",
    ],
    "Zurich 24": [
        "https://zuerich24.ch/sport",
        "https://zuerich24.ch/sport/eishockey",
        "https://zuerich24.ch/sport/fussball",
        "https://zuerich24.ch/dossiers",
    ],
    "Ticionline": [
        "https://www.tio.ch/newsblog",
        "https://www.tio.ch/sport",
        "https://www.tio.ch/agenda",
        "https://www.tio.ch/commenti",
        "https://www.tio.ch/focus",
    ],
    "TODAY": [
        "https://todayonline.com/latest-news",
        "https://todayonline.com/world",
    ],
    "Togo First": [
        "https://www.togofirst.com/fr/secteur-transports",
        "https://www.togofirst.com/fr/secteur-transport",
        "https://www.togofirst.com/fr",
        "https://www.togofirst.com/fr/entrepreneurs",
        "https://www.togofirst.com/fr/reformes-recentes",
        "https://www.togofirst.com/fr/secteur-agro",
    ],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Onboard new sites into JSON scraper catalogs")
    parser.add_argument("input", help="Path to the JSON file with sites to onboard")
    parser.add_argument("--catalog", help="Override the site catalog JSON path")
    parser.add_argument("--selectors", help="Override the selector map JSON path")
    parser.add_argument("--tracker", help="Override the category tracker JSON path")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds")
    parser.add_argument(
        "--limit-categories",
        type=int,
        default=8,
        help="Maximum discovered categories to store per site, excluding front page",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    runtime = default_runtime_config()
    if args.catalog:
        runtime.catalog_path = Path(args.catalog)
    if args.selectors:
        runtime.selectors_path = Path(args.selectors)
    if args.tracker:
        runtime.tracker_path = Path(args.tracker)

    payload = load_payload(args.input)
    catalog = load_json_model(runtime.catalog_path, SiteCatalog)
    selector_map = load_json_model(runtime.selectors_path, SelectorMap)
    tracker = load_json_model(runtime.tracker_path, CategoryPaginationTracker)

    catalog_by_name = {site.site_name: site for site in catalog.sites}
    selector_by_name = {site.site_name: site for site in selector_map.sites}
    tracker_by_name = {site.site_name: site for site in tracker.sites}

    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(headers=headers, follow_redirects=True, timeout=args.timeout) as client:
        for site in payload:
            is_active = True
            requested_base_url = BASE_URL_OVERRIDES.get(site["site_name"], site["base_url"])
            try:
                html, final_url = fetch_homepage(client, requested_base_url)
                final_url = canonical_site_base_url(requested_base_url, final_url)
                discovered = discover_site_details(site, html, final_url, args.limit_categories)
                if discovered["blocked"]:
                    is_active = False
            except Exception as exc:
                final_url = normalize_url(requested_base_url)
                override_categories = (
                    CATEGORY_OVERRIDES[site["site_name"]]
                    if site["site_name"] in CATEGORY_OVERRIDES
                    else None
                )
                discovered = {
                    "underlying_tech": "Custom CMS",
                    "category_urls": override_categories if override_categories is not None else (site.get("category_urls") or []),
                    "notes": (
                        f"Auto-onboarded {ensure_utc(utc_now()).date().isoformat()} without live discovery. "
                        f"Homepage fetch failed: {exc.__class__.__name__}: {exc}"
                    ),
                    "blocked": False,
                }
                is_active = False
            final_url = normalize_url(BASE_URL_OVERRIDES.get(site["site_name"], final_url))

            forced_inactive_reason = FORCE_INACTIVE_SITE_REASONS.get(site["site_name"])
            if forced_inactive_reason:
                is_active = False
                existing_notes = str(discovered.get("notes") or "")
                if existing_notes:
                    discovered["notes"] = f"{existing_notes} {forced_inactive_reason}"
                else:
                    discovered["notes"] = forced_inactive_reason

            catalog_entry = {
                "site_name": site["site_name"],
                "base_url": final_url,
                "country": normalize_required_text(site.get("country"), "Unknown"),
                "region": normalize_required_text(site.get("region"), "Unknown"),
                "language": normalized_site_language(
                    site["site_name"],
                    site.get("language"),
                    discovered.get("detected_lang"),
                ),
                "underlying_tech": discovered["underlying_tech"],
                "active": is_active,
                "preferred_scraping_tool": ScrapingTool.SCRAPLING.value,
                "scraping_history": [],
                "notes": discovered["notes"],
                "last_verified_at": None,
            }
            selector_entry = build_selector_entry(site["site_name"], discovered["underlying_tech"])
            tracker_entry = {
                "site_name": site["site_name"],
                "categories": [
                    {
                        "category_name": "front_page",
                        "category_url": final_url,
                        "total_known_pages": initial_known_pages(final_url, is_front_page=True),
                        "last_scraped_page_index": 0,
                    }
                ]
                + [
                    {
                        "category_name": derive_category_name(url),
                        "category_url": url,
                        "total_known_pages": initial_known_pages(url),
                        "last_scraped_page_index": 0,
                    }
                    for url in discovered["category_urls"]
                    if normalize_url(url) != normalize_url(final_url)
                ],
            }

            catalog_by_name[site["site_name"]] = catalog.__class__.model_validate(
                {"schema_version": catalog.schema_version, "sites": [catalog_entry]}
            ).sites[0]
            selector_by_name[site["site_name"]] = selector_map.__class__.model_validate(
                {"schema_version": selector_map.schema_version, "sites": [selector_entry]}
            ).sites[0]
            tracker_by_name[site["site_name"]] = tracker.__class__.model_validate(
                {"schema_version": tracker.schema_version, "sites": [tracker_entry]}
            ).sites[0]

    catalog.sites = sorted(catalog_by_name.values(), key=lambda item: item.site_name.casefold())
    selector_map.sites = sorted(selector_by_name.values(), key=lambda item: item.site_name.casefold())
    tracker.sites = sorted(tracker_by_name.values(), key=lambda item: item.site_name.casefold())

    save_json_model(runtime.catalog_path, catalog)
    save_json_model(runtime.selectors_path, selector_map)
    save_json_model(runtime.tracker_path, tracker)

    print(f"Onboarded {len(payload)} sites")
    print(f"Catalog: {runtime.catalog_path}")
    print(f"Selectors: {runtime.selectors_path}")
    print(f"Tracker: {runtime.tracker_path}")


def fetch_homepage(client: httpx.Client, base_url: str) -> tuple[str, str]:
    response = client.get(base_url)
    response.raise_for_status()
    return response.text, normalize_url(str(response.url))


def canonical_site_base_url(requested_url: str, fetched_url: str) -> str:
    requested = urlsplit(normalize_url(requested_url))
    fetched = urlsplit(normalize_url(fetched_url))
    requested_host = requested.netloc.lower().removeprefix("www.")
    fetched_host = fetched.netloc.lower().removeprefix("www.")

    same_site = False
    if requested_host and fetched_host:
        same_site = (
            requested_host == fetched_host
            or requested_host.endswith(f".{fetched_host}")
            or fetched_host.endswith(f".{requested_host}")
        )

    if same_site:
        scheme = fetched.scheme or requested.scheme or "https"
        netloc = fetched.netloc or requested.netloc
        return normalize_url(urlunsplit((scheme, netloc, "/", "", "")))

    scheme = requested.scheme or fetched.scheme or "https"
    netloc = requested.netloc or fetched.netloc
    return normalize_url(urlunsplit((scheme, netloc, "/", "", "")))


def discover_site_details(site: dict[str, Any], html: str, final_url: str, limit_categories: int) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    underlying_tech = detect_underlying_tech(html, soup)
    lower_text = soup.get_text(" ", strip=True).lower()
    blocked = any(indicator in lower_text for indicator in BLOCK_INDICATORS)
    override_categories = CATEGORY_OVERRIDES[site["site_name"]] if site["site_name"] in CATEGORY_OVERRIDES else None
    if override_categories is not None:
        category_urls = override_categories
    elif site.get("category_urls"):
        category_urls = site["category_urls"]
    else:
        category_urls = discover_categories(final_url, soup, limit_categories)
    lang = soup.html.get("lang") if soup.html else None
    notes = (
        f"Auto-onboarded {ensure_utc(utc_now()).date().isoformat()} from live homepage. "
        f"Detected html lang={lang or 'unknown'}."
    )
    if blocked:
        notes += " Homepage content looks like a bot-protection or access-check page."
    return {
        "underlying_tech": underlying_tech,
        "category_urls": category_urls,
        "notes": notes,
        "blocked": blocked,
        "detected_lang": lang,
    }


def load_payload(input_value: str) -> list[dict[str, Any]]:
    if input_value == "-":
        return json.loads(sys.stdin.read())
    return json.loads(Path(input_value).read_text(encoding="utf-8"))


def normalized_site_language(site_name: str, raw_language: Any, detected_lang: str | None) -> str:
    if site_name in LANGUAGE_OVERRIDES:
        return LANGUAGE_OVERRIDES[site_name]
    if isinstance(raw_language, str) and raw_language.strip():
        return raw_language.strip()
    if detected_lang and detected_lang.strip():
        return detected_lang.strip().split("-")[0]
    return "unknown"


def normalize_required_text(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def initial_known_pages(category_url: str, *, is_front_page: bool = False) -> int:
    """Seed pagination depth so historic mode can progress without manual edits."""

    if is_front_page:
        return 2
    return 3 if supports_implicit_pagination_seed(category_url) else 1


def supports_implicit_pagination_seed(category_url: str) -> bool:
    """Return True when `/page/{n}` probing is likely safe for this URL."""

    parsed = urlsplit(category_url)
    path = (parsed.path or "/").lower()
    if path in {"", "/"}:
        return False
    if re.search(r"\.[a-z0-9]{2,6}$", path):
        return False
    if any(token in path for token in ("/feed", "/rss", ".xml")):
        return False
    return True


def detect_underlying_tech(html: str, soup: BeautifulSoup) -> str:
    generator = soup.find("meta", attrs={"name": "generator"}) or soup.find("meta", attrs={"property": "generator"})
    content = (generator.get("content") if generator else "") or ""
    lower = f"{content} {html[:10000]}".lower()

    if "wordpress" in lower or "wp-content" in lower:
        return "WordPress"
    if "__next_data__" in lower or "/_next/" in lower:
        return "Next.js"
    if "drupal-settings-json" in lower or "drupalsettings" in lower:
        return "Drupal"
    if "astro-island" in lower or "astro-" in lower:
        return "Astro"
    if "elementor" in lower:
        return "WordPress"
    if "react" in lower or "data-reactroot" in lower:
        return "React"
    return "Custom CMS"


def discover_categories(base_url: str, soup: BeautifulSoup, limit_categories: int) -> list[str]:
    scored_candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    for selector in ("nav a[href]", "header a[href]", ".menu a[href]", ".nav a[href]", "#menu a[href]"):
        for anchor in soup.select(selector):
            href = anchor.get("href")
            text = anchor.get_text(" ", strip=True)
            if not text or len(text) > 64:
                continue
            full_url = normalize_candidate_url(base_url, href)
            if not full_url:
                continue
            if full_url in seen:
                continue
            path = urlsplit(full_url).path.rstrip("/")
            if path in ("", "/"):
                continue
            if BAD_CATEGORY_PATH.search(path):
                continue
            lowered_path = path.lower()
            if any(token in lowered_path for token in BAD_CATEGORY_SUBSTRINGS):
                continue
            if re.match(r"^/p/", path, flags=re.IGNORECASE):
                continue
            if looks_like_article_url(path):
                continue

            score = score_category_candidate(full_url, text)
            if score <= 0:
                continue
            seen.add(full_url)
            scored_candidates.append((score, full_url))

    scored_candidates.sort(key=lambda item: (-item[0], item[1]))
    return [url for _, url in scored_candidates[:limit_categories]]


def score_category_candidate(url: str, anchor_text: str) -> int:
    parts = urlsplit(url)
    path = parts.path.lower()
    query = parts.query.lower()
    text = anchor_text.strip().lower()
    segments = [segment for segment in path.split("/") if segment]

    score = 0
    if CATEGORY_HINTS.search(path):
        score += 6
    if CATEGORY_HINTS.search(text):
        score += 4
    if any(key in query for key in ("category", "cat=", "rubrique", "section", "topic")):
        score += 3
    if "id=" in query and "category" in path:
        score += 2
    if len(segments) <= 2:
        score += 1

    if BAD_CATEGORY_TEXT.search(text):
        score -= 8
    if any(token in path for token in ("/rss", "/feed", ".xml", "/wp-json", "/xmlrpc", "/categories")):
        score -= 8
    if re.search(r"\.(pdf|jpe?g|png|gif|webp|svg|zip|mp4|mp3|docx?|xlsx?|pptx?)($|[?#])", path, re.IGNORECASE):
        score -= 8
    if path.endswith(".html") and not CATEGORY_HINTS.search(path):
        score -= 4
    if len(segments) > 4:
        score -= 3
    if text.isdigit():
        score -= 3

    return score


def normalize_candidate_url(base_url: str, href: str | None) -> str | None:
    if not href or href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
        return None
    resolved = urljoin(base_url, href)
    base_parts = urlsplit(base_url)
    resolved_parts = urlsplit(resolved)
    if not resolved_parts.netloc.endswith(base_parts.netloc):
        return None
    return normalize_url(resolved)


def looks_like_article_url(path: str) -> bool:
    if re.search(r"\.(pdf|jpe?g|png|gif|webp|svg|zip|mp4|mp3|docx?|xlsx?|pptx?)($|[?#])", path, re.IGNORECASE):
        return True
    return bool(re.search(r"/\d{4}/|-\d{5,}$|/\d{5,}\.[a-z]{2,5}$|/[a-z0-9-]{20,}$", path, re.IGNORECASE))


def derive_category_name(url: str) -> str:
    path = urlsplit(url).path.strip("/")
    return path.replace("/", "_") or "front_page"


def build_selector_entry(site_name: str, underlying_tech: str) -> dict[str, Any]:
    article_link_selector = "article a[href], main article a[href], h2 a[href], h3 a[href]"
    if underlying_tech == "WordPress":
        article_link_selector = (
            "article a[href], .post a[href], .entry-title a[href], .jeg_post_title a[href], "
            ".td-module-title a[href], .wp-block-post-title a[href]"
        )
    elif underlying_tech in {"Next.js", "React", "Astro"}:
        article_link_selector = "article a[href], main h2 a[href], main h3 a[href], main a[href]"

    article_link_selectors = [
        {
            "type": "css",
            "value": article_link_selector,
            "attribute": "href",
            "multiple": True,
        },
        {
            "type": "css",
            "value": "main a[href], article a[href], h1 a[href], h2 a[href], h3 a[href], [class*='headline'] a[href], [class*='title'] a[href]",
            "attribute": "href",
            "multiple": True,
        },
        {
            "type": "css",
            "value": "a[href*='/article/'], a[href*='/news/'], a[href*='/story/'], a[href*='/202']",
            "attribute": "href",
            "multiple": True,
        },
    ]

    body_selectors = [
        {"type": "css", "value": "[itemprop='articleBody'] p", "multiple": True},
        {"type": "css", "value": ".entry-content p, .post-content p, .article-content p, .article-body p", "multiple": True},
        {"type": "css", "value": ".td-post-content p, .jeg_post_content p, .single-content p", "multiple": True},
        {"type": "css", "value": "article p", "multiple": True},
        {"type": "css", "value": "main p", "multiple": True},
    ]

    return {
        "site_name": site_name,
        "article_link_selectors": article_link_selectors,
        "canonical_url_selector": {
            "type": "meta",
            "value": "og:url",
            "attribute": "content",
            "multiple": False,
        },
        "fields": {
            "article_title": {
                "selectors": [
                    {"type": "json_ld", "value": "headline", "multiple": False},
                    {"type": "meta", "value": "og:title", "attribute": "content", "multiple": False},
                    {"type": "css", "value": "h1", "multiple": False},
                ],
                "required": True,
                "postprocess": ["strip", "normalize_whitespace"],
                "default": None,
            },
            "author": {
                "selectors": [
                    {"type": "json_ld", "value": "author.name", "multiple": False},
                    {"type": "meta", "value": "author", "attribute": "content", "multiple": False},
                    {"type": "css", "value": "[rel='author'], .author, .byline, [class*='author'], [class*='byline']", "multiple": False},
                ],
                "required": False,
                "postprocess": ["strip", "normalize_whitespace"],
                "default": None,
            },
            "article_body": {
                "selectors": body_selectors,
                "required": True,
                "postprocess": ["strip", "normalize_whitespace", "join_paragraphs"],
                "default": None,
            },
            "tags": {
                "selectors": [
                    {"type": "meta", "value": "news_keywords", "attribute": "content", "multiple": False},
                    {"type": "css", "value": "a[rel='tag'], .tags a, .tagcloud a, [class*='tag'] a", "multiple": True},
                ],
                "required": False,
                "postprocess": ["strip", "normalize_whitespace", "dedupe_list"],
                "default": [],
            },
            "date_published": {
                "selectors": [
                    {"type": "json_ld", "value": "datePublished", "multiple": False},
                    {"type": "meta", "value": "article:published_time", "attribute": "content", "multiple": False},
                    {"type": "meta", "value": "publish-date", "attribute": "content", "multiple": False},
                    {"type": "meta", "value": "pubdate", "attribute": "content", "multiple": False},
                    {"type": "css", "value": "time[datetime]", "attribute": "datetime", "multiple": False},
                ],
                "required": True,
                "input_formats": [],
                "timezone": "UTC",
                "output_format": "iso8601",
                "postprocess": ["strip", "normalize_whitespace"],
                "default": None,
            },
            "article_url": {
                "selectors": [
                    {"type": "meta", "value": "og:url", "attribute": "content", "multiple": False},
                    {"type": "xpath", "value": "//link[@rel='canonical']/@href", "multiple": False},
                ],
                "required": True,
                "normalize_to_canonical": True,
                "postprocess": ["strip", "normalize_whitespace", "trim_trailing_slash"],
                "default": None,
            },
            "url_hash": {
                "source_field": "article_url",
                "algorithm": "md5",
            },
            "main_image_url": {
                "selectors": [
                    {"type": "meta", "value": "og:image", "attribute": "content", "multiple": False},
                    {"type": "meta", "value": "twitter:image", "attribute": "content", "multiple": False},
                ],
                "required": False,
                "normalize_to_canonical": True,
                "postprocess": ["strip", "normalize_whitespace", "trim_trailing_slash"],
                "default": None,
            },
            "seo_description": {
                "selectors": [
                    {"type": "meta", "value": "description", "attribute": "content", "multiple": False},
                    {"type": "meta", "value": "og:description", "attribute": "content", "multiple": False},
                ],
                "required": False,
                "postprocess": ["strip", "normalize_whitespace"],
                "default": None,
            },
        },
    }


if __name__ == "__main__":
    main()

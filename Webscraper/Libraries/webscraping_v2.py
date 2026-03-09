from __future__ import annotations

import os
import sys
import re
import time
import random
import signal
import logging
import logging.config
import traceback
from contextlib import suppress
from datetime import datetime
from typing import List, Tuple, Optional, Set, Dict
from urllib.parse import urlparse, urldefrag
import tempfile
import shutil
import pathlib
import unicodedata

import pandas as pd
import tldextract
import dateparser
from dateutil import parser
from tqdm import tqdm
from bs4 import BeautifulSoup
import multiprocessing as mp
import asyncio
from concurrent.futures import ProcessPoolExecutor, as_completed

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait

from newsplease import NewsPlease

# ✅ keep ONLY this relative import; DO NOT import Libraries.webscraping_v2 anywhere
from . import my_logger

import json as _json
import hashlib
import pandas as _pd
import re as _re

class _ProcessingShim:
    @staticmethod
    def remove_whitespaces(s: str) -> str:
        try:
            return _re.sub(r"\s+", "", s or "")
        except Exception:
            return s or ""

    @staticmethod
    def clean(s: str) -> str:
        try:
            cleaned = s or ""
            cleaned = _re.sub(r"[ \t]+", " ", cleaned)
            cleaned = cleaned.replace("\u200b", "").strip()
            return cleaned
        except Exception:
            return s or ""

    @staticmethod
    def hash_url(url: str) -> str:
        return hashlib.md5((url or "").encode("utf-8", errors="ignore")).hexdigest()

processing = _ProcessingShim()

class _JsonReaderShim:
    @staticmethod
    def read_json(path: str):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return _json.load(f)
        except Exception:
            return None

json_reader = _JsonReaderShim()

class _SaveShim:
    @staticmethod
    def saving_articles(data, infer_datetime: bool = True):
        if isinstance(data, _pd.DataFrame):
            df = data.copy()
        else:
            try:
                df = _pd.DataFrame(list(data))
            except Exception:
                df = _pd.DataFrame()
        if infer_datetime and not df.empty:
            for col in ["date_publish", "date_download", "date_modify"]:
                if col in df.columns:
                    with _pd.option_context("mode.chained_assignment", None):
                        try:
                            df[col] = _pd.to_datetime(df[col], errors="coerce", utc=True)
                        except Exception:
                            pass
        return df

save = _SaveShim()

# Global seen-hash set
LOCAL_SEEN_HASHES: Set[str] = set()

class _DyShim:
    @staticmethod
    def CheckIfExistsInWebscrapes(_cfg, url_hash: str) -> bool:
        try:
            return url_hash in LOCAL_SEEN_HASHES
        except Exception:
            return False

    @staticmethod
    def SaveResultsWebscrapers(df, _cfg):
        return True

dy = _DyShim()
# ------------------------------------------------------

# ---------------- Logging & globals -------------------
logger = my_logger.setup_logger("Webscraper")

LOGGING_CFG = {
    "version": 1,
    "disable_existing_loggers": False,
    "loggers": {
        "newsplease": {"level": "WARNING", "propagate": False},
        "newsplease.crawler": {"level": "WARNING", "propagate": False},
        "newsplease.crawler.extractor": {"level": "WARNING", "propagate": False},
        "readability": {"level": "WARNING", "propagate": False},
        "newspaper": {"level": "WARNING", "propagate": False},
        "dateparser": {"level": "WARNING", "propagate": False},
        "langdetect": {"level": "WARNING", "propagate": False},
    },
}
logging.config.dictConfig(LOGGING_CFG)

_STOP = False
def _install_signal_handlers_once():
    def handler(signum, frame):
        global _STOP
        _STOP = True
        raise KeyboardInterrupt
    if hasattr(signal, "SIGINT"):
        with suppress(Exception):
            signal.signal(signal.SIGINT, handler)
    if hasattr(signal, "SIGTERM"):
        with suppress(Exception):
            signal.signal(signal.SIGTERM, handler)
_install_signal_handlers_once()

# ---------------- Small helpers -----------------------
def _safe_list(v, *, default=None):
    if default is None:
        default = []
    return list(v) if isinstance(v, (list, tuple)) else (default.copy())

def _safe_dict(v, *, default=None):
    if default is None:
        default = {}
    return dict(v) if isinstance(v, dict) else (default.copy())

def _should_stop() -> bool:
    return _STOP

def _make_chrome_options() -> Options:
    options = Options()
    options.add_argument("--headless=new")
    options.page_load_strategy = "eager"
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--enable-javascript")
    options.add_argument("--window-size=1366,2000")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-notifications")
    options.add_argument("--allow-insecure-localhost")
    options.add_argument("--ignore-ssl-errors")
    options.add_argument("--incognito")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-breakpad")
    options.add_argument("--disable-client-side-phishing-detection")
    options.add_argument("--disable-default-apps")
    options.add_argument("--metrics-recording-only")
    options.add_argument("--safebrowsing-disable-auto-update")
    options.add_argument("--no-first-run")
    options.add_argument("--disable-features=Translate,AcceptCHFrame,MediaRouter,OptimizationHints,AutoExpandDetailsElement")
    if os.getenv("WS_BLOCK_IMAGES", "0") == "1":
        options.add_experimental_option("prefs", {
            "profile.managed_default_content_settings.images": 2,
            "profile.default_content_setting_values.notifications": 2,
        })
    options.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 11_2_1) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.1"
    )
    return options

def _new_browser(base_options: Options | None = None):
    options = _make_chrome_options() if base_options is None else _make_chrome_options()
    try:
        temp_profile = tempfile.mkdtemp(prefix="ws_chrome_profile_")
        options.add_argument(f"--user-data-dir={temp_profile}")
    except Exception as e:
        logger.warning(f"Could not create temp profile dir: {e}")
        temp_profile = None
    options.add_argument("--profile-directory=Default")
    options.add_argument("--remote-debugging-port=0")
    driver = webdriver.Chrome(options=options)
    setattr(driver, "_temp_profile_dir", temp_profile)
    with suppress(Exception):
        driver.set_page_load_timeout(30)
    with suppress(Exception):
        driver.set_script_timeout(30)
    if os.getenv("WS_BLOCK_MEDIA", "0") == "1":
        with suppress(Exception):
            driver.execute_cdp_cmd("Network.enable", {})
            driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": [
                "*.png","*.jpg","*.jpeg","*.gif","*.webp","*.svg",
                "*.woff","*.woff2","*.ttf","*.otf",
                "*.mp4","*.avi","*.mov","*.wmv"
            ]})
    return driver

def _quit_browser(browser):
    if not browser:
        return
    with suppress(Exception):
        browser.quit()
    with suppress(Exception):
        svc = getattr(browser, "service", None)
        proc = getattr(svc, "process", None)
        if proc:
            proc.kill()
    with suppress(Exception):
        if getattr(browser, "service", None):
            browser.service.stop()
    tmp = getattr(browser, "_temp_profile_dir", None)
    if tmp and os.path.isdir(tmp):
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception as e:
            logger.warning(f"Could not remove temp profile dir {tmp}: {e}")

def _safe_get(driver, url, attempts: int = 2) -> bool:
    for i in range(attempts):
        if _should_stop():
            return False
        try:
            driver.get(url)
            return True
        except Exception as e:
            logger.info("driver.get failed (%s/%s) for %s: %s", i + 1, attempts, url, e)
            time.sleep(1 + i)
    return False

# ---------- Seen-hash loader (exact column) -----------
def _load_seen_hashes_exact(out_csv_path: str) -> Set[str]:
    seen: Set[str] = set()
    if not out_csv_path or not os.path.isfile(out_csv_path):
        return seen
    try:
        s = pd.read_csv(out_csv_path, usecols=["source_url_hash"], dtype=str)["source_url_hash"]
        vals = s.dropna().astype(str).str.strip()
        seen.update(v for v in vals.tolist() if v)
        logger.info(f"Loaded {len(seen)} existing URL hashes from 'source_url_hash'.")
    except ValueError as e:
        logger.warning(f"'source_url_hash' not found in output CSV: {e}")
    except Exception as e:
        logger.warning(f"Could not load seen hashes from {out_csv_path}: {e}")
    return seen

# ============================ Scraper =================
class WebScraperV2:
    def __init__(
        self,
        url="",
        pages_urls=[],
        anti_robot=False,
        load_more_button=False,
        alt_source_domain="",
        config_data={"dynamoDB": ""},
        selections_file="Scraper_Selection/scraping_results.json",
    ):
        self.options = _make_chrome_options()
        self.URL = url

        self.url_parser = urlparse(url)
        if self.url_parser.hostname is None:
            if isinstance(pages_urls, List):
                if len(pages_urls) > 0:
                    self.url_parser = urlparse(pages_urls[0])
                elif url != "":
                    self.url_parser = urlparse("https://" + url)
            else:
                self.url_parser = urlparse(pages_urls)

        self.url_scheme = self.url_parser.scheme or "https"
        self.base_url = (
            f"{self.url_scheme}://{self.url_parser.hostname}"
            if self.url_parser.hostname else ""
        )

        self.anti_robot = anti_robot
        self.load_more_button = (
            "" if (len(str(load_more_button)) <= 3 or str(load_more_button) == "False")
            else str(load_more_button)
        )
        self.alt_source_domain = str(alt_source_domain)
        self.config_data = _safe_dict(config_data, default={"dynamoDB": ""})
        self.selections_file = selections_file
        self.selections = self.load_selection(selections_file=selections_file, url=self.base_url)

        self.scraper_functions = {
            "Interactive": self.run_interactive_scraper,
            "Newsplease": self.run_newsplease_scraper,
            "default": self.run_newsplease_scraper,
        }

    # ---------- selections ----------
    def load_selection(self, selections_file="", url=None):
        if selections_file == "":
            selections_file = self.selections_file
        if url is None:
            url = self.base_url
        if url and url[0] != "/":
            url = url + "/"
        if not os.path.isfile(selections_file):
            return None
        data = json_reader.read_json(selections_file)
        if not data:
            return None
        selections = data[0]
        if url in selections.keys():
            return selections[url]
        if "http" not in url:
            if "https://" + url in selections.keys():
                return selections["https://" + url]
            if "http://" + url in selections.keys():
                return selections["http://" + url]
        return None

    def get_scrapers(self):
        if self.selections is None:
            return ["default"]
        scrapers = []
        for element in self.selections.keys():
            scraper = self.selections[element].get("scraper")
            if scraper and scraper not in scrapers:
                scrapers.append(scraper)
        return scrapers

    # ---------- chrome lifecycle ----------
    def restart_chrome(self, browser):
        _quit_browser(browser)
        return _new_browser(self.options)

    def kill_chrome(self, browser):
        _quit_browser(browser)

    # ---------- utilities ----------
    def cloudflare_check(self, title):
        try:
            return "Cloudflare" in title.text
        except Exception:
            return False

    # ---------- link collection ----------
    def get_links_to_scrape_category(self, url, pages=1):
        if _should_stop():
            return []
        links_to_scrape = []
        get_links_browser = None
        try:
            get_links_browser = _new_browser(self.options)
            for p in range(1, pages + 1):
                if _should_stop():
                    break
                if p > 1 and (p % 10 == 0 or p == pages):
                    logger.info(f"Getting links to scrape for {url.replace(self.URL,'')}: {p}/{pages}")
                try:
                    if len(self.load_more_button) > 3 and p == 1:
                        if not _safe_get(get_links_browser, url):
                            continue
                    if len(self.load_more_button) > 3:
                        get_links_browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        time.sleep(random.randint(1, 2))
                        if self.load_more_button != "Scroll Down":
                            clicked = False
                            for button in get_links_browser.find_elements(By.XPATH, f"//a[text()='{self.load_more_button}']"):
                                clicked = True
                                button.click()
                                time.sleep(random.randint(1, 2))
                            if not clicked:
                                for button in get_links_browser.find_elements(By.XPATH, f"//span[text()='{self.load_more_button}']"):
                                    button.click()
                                    time.sleep(random.randint(1, 2))
                    else:
                        link = url.format(p=str(p))
                        if not _safe_get(get_links_browser, link):
                            continue

                    if self.anti_robot:
                        time.sleep(random.randint(1, 2))

                    content = get_links_browser.page_source
                    soup = BeautifulSoup(content, "html5lib")

                    if self.cloudflare_check(soup.find("title")):
                        try:
                            links_to_scrape.append(link)
                        except NameError:
                            links_to_scrape.append(url)
                        continue

                    for a in soup.find_all("a"):
                        if _should_stop():
                            break
                        href = a.get("href")
                        if not href:
                            continue
                        if self.url_parser.hostname and self.url_parser.hostname in href:
                            if "http" in href:
                                links_to_scrape.append(href)
                            else:
                                links_to_scrape.append(f"{self.url_scheme}://{href}")
                        elif not href.startswith("http") and not href.startswith("/"):
                            candidate = f"{self.base_url}/{href}".rstrip("/")
                            if self.base_url in candidate:
                                links_to_scrape.append(candidate)
                        elif not href.startswith("http") and href.startswith("/"):
                            candidate = f"{self.base_url}{href}"
                            if self.base_url in candidate:
                                links_to_scrape.append(candidate)

                except WebDriverException:
                    logger.info(f"Unable to get links to scrape for page: {p}")
                    traceback.print_exc()
                    _quit_browser(get_links_browser)
                    get_links_browser = _new_browser(self.options)
                    continue
                except KeyboardInterrupt:
                    logger.info("Keyboard interrupt. Quitting scraper.")
                    raise
                except Exception:
                    logger.info(f"Unable to get links to scrape for page: {p}")
                    traceback.print_exc()
                    continue
        finally:
            _quit_browser(get_links_browser)
        return links_to_scrape

    def get_news_please_info(self, url):
        return NewsPlease.from_url(url, timeout=300)

    # ---------- date utils ----------
    async def search_for_date(self, element_to_search, high_level_element_to_search, html_soup):
        try:
            parsed_date = dateparser.parse(str(element_to_search))
            return parsed_date
        except ValueError:
            pass
        parsed_date = dateparser.search.search_dates(str(element_to_search))
        if parsed_date:
            return parsed_date[0][1]
        parsed_date = dateparser.search.search_dates(str(getattr(high_level_element_to_search, "text", "")))
        if parsed_date:
            return parsed_date[0][1]
        parsed_date = dateparser.search.search_dates(str(html_soup.text))
        if parsed_date:
            return parsed_date[0][1]
        return None

    # ---------- Interactive scraper ----------
    async def run_interactive_scraper(self, urls):
        if _should_stop():
            return pd.DataFrame()
        webscrapes_df = pd.DataFrame()
        if self.selections is None:
            return webscrapes_df

        current_url_results = self.selections
        for url in urls:
            if _should_stop():
                break
            browser = None
            try:
                browser = _new_browser(self.options)
                if not _safe_get(browser, url):
                    continue
                try:
                    WebDriverWait(browser, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                except TimeoutException:
                    logger.info("Timeout while waiting for page content. Skipping page.")
                    continue

                soup = BeautifulSoup(browser.page_source, "html.parser")

                if "type" in current_url_results.get("high_level_element", {}).keys():
                    h = current_url_results["high_level_element"]
                    if h["type"] == "class":
                        high_level_element = soup.find(class_=h["value"]) or soup
                    elif h["type"] == "property":
                        high_level_element = soup.find(property=h["value"])
                    elif h["type"] == "id":
                        high_level_element = soup.find(id=h["value"])
                    elif h["type"] == "none":
                        high_level_element = soup
                    else:
                        high_level_element = soup.find(h["value"])
                else:
                    high_level_element = soup

                result = {}
                for key, selector in current_url_results.items():
                    if key == "high_level_element":
                        continue
                    if selector.get("scraper") != "Interactive":
                        continue
                    t = selector.get("type")
                    if t == "class":
                        element = high_level_element.find(class_=selector["value"])
                        result[key] = element.text.strip() if element else ""
                    elif t == "property":
                        element = high_level_element.find(property=selector["value"])
                        result[key] = element.text.strip() if element else ""
                    elif t == "id":
                        element = high_level_element.find(id=selector["value"])
                        result[key] = element.text.strip() if element else ""
                    elif t == "none":
                        result[key] = ""

                try:
                    pd.to_datetime(result.get("date_publish"))
                except Exception:
                    result["date_publish"] = await self.search_for_date(
                        result.get("date_publish", ""), result.get("body", ""), soup
                    )
                webscrapes_df = pd.concat([webscrapes_df, pd.DataFrame([result])], ignore_index=True)
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt. Quitting interactive scraper.")
                raise
            except Exception:
                traceback.print_exc()
                continue
            finally:
                _quit_browser(browser)

        return webscrapes_df

    # ---------- NewsPlease scraper ----------
    async def run_newsplease_scraper(self, url):
        df = await self.scrape_article_info(url)
        return df

    # ---------- Collation ----------
    def collate_scraper_results(self, results, scraper_dict):
        selections = self.selections
        colated_results = pd.DataFrame()
        keys = [
            "authors","date_download","date_publish","description","image_url",
            "language","source_domain","body","title","url","source_url_hash",
        ]
        if selections is None:
            return results[scraper_dict["default"]]
        for element in selections.keys():
            sel = selections[element]
            scraper = sel.get("scraper")
            if not scraper:
                continue
            colated_results[element] = results[scraper][element]
        for key in keys:
            if key not in colated_results.columns:
                colated_results[key] = results[scraper_dict["default"]][key]
        return colated_results[keys]

    # ---------- Script detection helpers ----------
    def is_korean_char(self, char):
        try:
            name = unicodedata.name(char)
            return "HANGUL" in name or "CJK" in name
        except ValueError:
            return False

    def is_chinese_char(self, char):
        try:
            return "CJK" in unicodedata.name(char)
        except ValueError:
            return False

    def ratio_script_characters(self, text, char_check_function):
        if not text:
            return 0.0
        count = sum(1 for char in text if char_check_function(char))
        return count / len(text)

    # ---------- Per-link scrape ----------
    async def scrape_single_link(self, link: str) -> dict | None:
        if _should_stop():
            return None
        logger.info(f"Scraping: {link}")
        if link.endswith(".pdf"):
            return None

        browser = None
        try:
            try:
                article = NewsPlease.from_url(link, timeout=30)
            except TimeoutError:
                logger.info("Timeout error. Skipping page.")
                return None
            except Exception as e:
                logger.info(f"Error scraping page (NewsPlease): {e}")
                return None

            if _should_stop():
                return None

            browser = _new_browser(self.options)
            if not _safe_get(browser, link):
                return None

            if self.anti_robot:
                time.sleep(random.randint(1, 2))
                browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                browser.execute_script("window.scrollTo(document.body.scrollHeight, 0);")

            try:
                WebDriverWait(browser, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                content = browser.page_source
            except TimeoutException:
                logger.info("Timeout while waiting for page content. Skipping page.")
                return None

            soup = BeautifulSoup(content, "html5lib")

            if self.cloudflare_check(soup.find("title")) and not article.maintext:
                logger.info(f"Skipping: {link} - Cloudflare")
                return None

            date_publish = ""
            date_url = self.find_date_in_url(link)
            formatted_date_str = date_url.strftime("%Y-%m-%dT%H:%M:%S") if date_url else None

            if date_publish == "":
                try:
                    date_publish = article.date_publish
                    if date_publish is not None:
                        date_publish = parser.parse(str(date_publish))
                except Exception:
                    pass

                if formatted_date_str:
                    formatted_date_dt = datetime.strptime(formatted_date_str, "%Y-%m-%dT%H:%M:%S")
                    if (date_publish != "" and date_publish and formatted_date_dt and date_publish < formatted_date_dt):
                        date_publish = formatted_date_str

            if date_publish == "":
                return None

            if self.is_date_in_future(str(date_publish)):
                logger.info(f"Skipping: {link} - date in the future")
                return None

            body = article.maintext or ""
            if not body or len(processing.remove_whitespaces(body)) < 200:
                chunks = []
                for a in soup.find_all("article"):
                    chunks.append(a.get_text(separator="\n"))
                    break
                if len(processing.remove_whitespaces("".join(chunks))) < 100:
                    for p in soup.find_all("p"):
                        if any(p.find_parents(tag) for tag in ["aside","footer","nav","header","script","style","noscript","form","iframe","svg","img"]):
                            continue
                        chunks.append(p.get_text(separator="\n"))
                all_text = "\n".join(chunks)
                if article.description and len(processing.remove_whitespaces(all_text)) < 100:
                    all_text = article.description
                if len(processing.remove_whitespaces(all_text)) < 100:
                    if self.ratio_script_characters(all_text, self.is_chinese_char) <= 0.2:
                        logger.info(f"Skipping due to insufficient text: {link}")
                        return None
                    else:
                        if len(processing.remove_whitespaces(all_text)) < 20:
                            logger.info(f"Skipping due to insufficient text: {link}")
                        return None
                body = processing.clean(all_text).strip()

            source_domain = self.alt_source_domain if len(self.alt_source_domain) > 4 else article.source_domain

            result = {
                "authors": article.authors,
                "date_download": article.date_download,
                "date_publish": date_publish,
                "description": article.description,
                "image_url": [article.image_url],
                "language": article.language,
                "source_domain": source_domain,
                "body": body,
                "title": article.title,
                "url": link,
                "source_url_hash": processing.hash_url(link),
            }
            return result

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt. Quitting scraper.")
            raise
        except Exception as e:
            traceback.print_exc()
            logger.info(f"Error scraping page: {e}")
            return None
        finally:
            _quit_browser(browser)

    # ---------- Batch article scrape ----------
    async def scrape_article_info(self, links_to_scrape):
        if _should_stop():
            return pd.DataFrame()
        all_articles = []
        webscrapes_df = pd.DataFrame()

        for lts in links_to_scrape:
            if _should_stop():
                break
            try:
                scraped_article = await asyncio.wait_for(self.scrape_single_link(lts), timeout=300)
            except asyncio.TimeoutError:
                logger.info("Timeout error. Skipping page.")
                continue
            if isinstance(scraped_article, dict):
                all_articles.append(scraped_article)

        if len(all_articles) > 0 and "date_publish" in all_articles[0].keys():
            try:
                webscrapes_df = save.saving_articles(all_articles, infer_datetime=True)
            except KeyError as e:
                logger.info(f"Not saving webscrapes: KeyError: {e}")
        return webscrapes_df

    # ---------- misc utils ----------
    def is_date_in_future(self, date_str):
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
            return date_obj > datetime.now()
        except ValueError:
            return False

    def find_date_in_url(self, url):
        date_pattern = r"/(\d{4})(?:/(\d{2})(?:/(\d{2}))?)?"
        title_pattern = r"/(\d{4}-\d{2}-\d{2})"

        match = re.search(date_pattern, url)
        if match:
            year, month, day = match.groups()
            if month and day:
                date_str = f"{year}-{month}-{day}"
                fmt = "%Y-%m-%d"
            elif month:
                date_str = f"{year}-{month}-01"
                fmt = "%Y-%m-%d"
            else:
                date_str = f"{year}-01-01"
                fmt = "%Y-%m-%d"
            with suppress(ValueError):
                return datetime.strptime(date_str, fmt)

        match = re.search(title_pattern, url)
        if match:
            with suppress(ValueError):
                return datetime.strptime(match.group(1), "%Y-%m-%d")
        return None

    def translate_arabic_date(self, text):
        months = {
            "كانون الثاني": 1, "شباط": 2, "آذار": 3, "نيسان": 4, "أيار": 5, "حزيران": 6,
            "تموز": 7, "آب": 8, "ايلول": 9, "تشرين الاول": 10, "تشرين الثاني": 11, "كانون الأول": 12,
        }
        month = next((m for k, m in months.items() if k in text), datetime.today().month)
        year = re.findall(r"\b\d{4}\b|$", text)[0] or str(datetime.today().year)
        day = re.findall(r"\b\d{1,2}\b|$", text)[0] or str(datetime.today().day)
        date = datetime(year=int(year), month=int(month), day=int(day))
        return date.strftime("%Y-%m-%dT%H-%M-%S")

# ============================ URL helpers =============
def is_valid_url(url):
    try:
        parsed_url = urlparse(url)
        return all([parsed_url.scheme, parsed_url.netloc])
    except Exception:
        return False

def extract_domain(url):
    extracted = tldextract.extract(url)
    subdomain = extracted.subdomain
    if subdomain and subdomain.lower() == "www":
        return subdomain + "." + extracted.domain + "." + extracted.suffix
    elif subdomain:
        return subdomain + "." + extracted.domain + "." + extracted.suffix
    else:
        return extracted.domain + "." + extracted.suffix

def get_core_domain(url):
    extracted = tldextract.extract(url)
    return extracted.domain + "." + extracted.suffix

# ============================ Link filtering ==========
def process_link(link, unique_links, url, config_data, test_scraper):
    link = urldefrag(link).url
    url_hash = processing.hash_url(link)
    if url_hash in LOCAL_SEEN_HASHES:
        return False

    if not test_scraper and dy.CheckIfExistsInWebscrapes(config_data.get("dynamoDB", ""), url_hash):
        return False

    allow_cross_domain = bool(config_data.get("direct_links"))
    if not allow_cross_domain and get_core_domain(link) != get_core_domain(url):
        return False

    if not link.startswith("http"):
        link = "https://" + link

    parsed_link = urlparse(link)
    if parsed_link.path == "":
        return False

    if len(link) <= len(url) + 5 and not allow_cross_domain:
        return False

    non_article_endings = [
        ".jpg",".jpeg",".png",".gif",".bmp",".tiff",".svg",
        ".mp3",".wav",".ogg",".m4a",".mp4",".avi",".mov",".wmv",
        ".pdf",".doc",".docx",".xls",".xlsx",".ppt",".pptx",
        ".zip",".rar",".7z",".tar.gz",".exe",".dll",".dmg",".apk",
        ".css",".js",".json",".ico",".rss",".ttf",".otf",".woff",".woff2",
        "/login","/signup","/logout","/register","/signin",
        "advertisement","/category","/categories","/search","/search?",
        "/lost-password","/forgot-password","/reset-password",
        "/lostpassword","/forgotpassword","/resetpassword","?page=",
        "/archive-","/archive","/archives","/tag",
        "/font-size","/font","/info","/introduction","/lang",
        "/sponsor","/sponsored","/program",
        "/news","/editorial","/programmes","/group","/groups",
        "/subscription","/subscriptions",
        "/world","/politics","/business","/technology","/sports",
        "/entertainment","/health","/science","/travel","/style",
        "/monde","/politique","/affaires","/technologie","/divertissement",
        "/sante","/science","/voyage",
    ]
    lower = link.strip("/").lower()
    for ending in non_article_endings:
        if lower.endswith(ending):
            return False

    links_to_ignore = [r"\/font-size", r"\/font.*", r"\/lang\/.*"]
    for pat in links_to_ignore:
        if re.search(pat, link):
            return False

    if link.count(":") >= 2:
        return False

    if not is_valid_url(link):
        return False

    if re.search(r"\/\d{4}(?:\/\d{2}(?:\/\d{2})?)?\/?$", link):
        return False
    if re.search(r"\/contact", link):
        return False
    if re.search(r"\/tag\/[\w-]+\/", link):
        return False
    if re.search(r"\/page\/\d+\/?", link):
        return False

    unique_links.append(link)
    return True

# ---------------- Worker helpers ----------------------
def _process_link_return(link: str, url: str, config_data: dict, test_scraper: bool) -> Optional[str]:
    tmp: List[str] = []
    ok = process_link(link, tmp, url, config_data, test_scraper)
    if ok and tmp:
        return tmp[0]
    return None

def _worker_init():
    with suppress(Exception):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    with suppress(Exception):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

def _filter_link_worker(args: Tuple[str, str, dict, bool]) -> Optional[str]:
    link, url, config_data, test_scraper = args
    try:
        return _process_link_return(link, url, config_data, test_scraper)
    except Exception:
        return None

def _append_results_to_csv(webscrapes_df: pd.DataFrame, out_csv_path: Optional[str]) -> None:
    if not out_csv_path:
        return
    if not isinstance(webscrapes_df, pd.DataFrame) or webscrapes_df.empty:
        return
    try:
        if "source_url_hash" in webscrapes_df.columns:
            mask = ~webscrapes_df["source_url_hash"].astype(str).isin(LOCAL_SEEN_HASHES)
            webscrapes_df = webscrapes_df.loc[mask].copy()
        if webscrapes_df.empty:
            return
        mode = "a" if os.path.isfile(out_csv_path) else "w"
        header = not os.path.isfile(out_csv_path)
        webscrapes_df.to_csv(out_csv_path, index=False, mode=mode, header=header)
        if "source_url_hash" in webscrapes_df.columns:
            for _h in webscrapes_df["source_url_hash"].dropna().astype(str).tolist():
                LOCAL_SEEN_HASHES.add(_h)
    except Exception as _e:
        logger.warning(f"Failed to append to {out_csv_path}: {_e}")

# ============================ Runner ==================
def webscrape(
    name,
    url="",
    pages_urls=[],
    num_pages=1,
    anti_robot=False,
    load_more_button="",
    alt_source_domain="",
    config_data={},
    test_scraper=False,
):
    """
    Main function that runs the scrape (public API unchanged).
    """
    global LOCAL_SEEN_HASHES
    LOCAL_SEEN_HASHES = set(config_data.get("local_seen_hashes", set()) or set())
    out_csv_path: Optional[str] = config_data.get("out_csv_path")
    direct_links: Optional[List[str]] = config_data.get("direct_links")

    # Load existing hashes from output CSV ('source_url_hash' only)
    if out_csv_path and os.path.isfile(out_csv_path):
        prev_hashes = _load_seen_hashes_exact(out_csv_path)
        before = len(LOCAL_SEEN_HASHES)
        LOCAL_SEEN_HASHES |= prev_hashes
        logger.info(
            f"Loaded {len(LOCAL_SEEN_HASHES) - before} additional URL hashes from output CSV (total={len(LOCAL_SEEN_HASHES)})."
        )

    pages_urls = _safe_list(pages_urls)
    config_data = _safe_dict(config_data)

    raw_bs = config_data.get("batch_size", 10)
    try:
        batch_size = int(raw_bs)
    except Exception:
        batch_size = 10

    scraper = WebScraperV2(
        url,
        pages_urls=pages_urls,
        anti_robot=anti_robot,
        load_more_button=load_more_button,
        alt_source_domain=alt_source_domain,
        config_data=config_data,
        selections_file="Scraper_Selection/scraping_results.json",
    )

    unique_links: List[str] = []
    links: List[str] = []
    new_articles = pd.DataFrame()

    scraper_dict = {
        "Interactive": scraper.run_interactive_scraper,
        "Newsplease": scraper.run_newsplease_scraper,
        "default": "Newsplease",
    }

    try:
        if _should_stop():
            return pd.DataFrame()

        link_category_name = url
        if len(url.split("/")) > 2:
            link_category_name = url.split("/")[2]
        if len(pages_urls) == 1:
            link_category_name = f"{link_category_name}_{pages_urls[0].replace(url,'')}"

        # Discovery or direct list
        if direct_links:
            links = [lnk.strip() for lnk in direct_links if isinstance(lnk, str) and lnk.strip()]
            logger.info(f"Using {len(links)} direct links.")
        else:
            if len(pages_urls) < 1:
                links += scraper.get_links_to_scrape_category(url)
            else:
                for pgs in pages_urls:
                    if _should_stop():
                        break
                    links += scraper.get_links_to_scrape_category(pgs, num_pages)

        if _should_stop():
            return pd.DataFrame()

        links = list(set(links))

        # Filter links in parallel
        ws = config_data.get("webscraper", {})
        try:
            divisor = int(ws.get("multiprocessing", 2))
        except Exception:
            divisor = 2
        try:
            num_processes = max(1, mp.cpu_count() // max(1, divisor))
        except Exception:
            num_processes = max(1, mp.cpu_count() // 2)

        logger.info(f"Checking {len(links)} links using {num_processes} processes...")
        args_iter = [(lnk, url, config_data, test_scraper) for lnk in links]

        try:
            with ProcessPoolExecutor(max_workers=int(num_processes), initializer=_worker_init) as ex:
                futures = [ex.submit(_filter_link_worker, a) for a in args_iter]
                with tqdm(total=len(futures), desc=f"Checking links {link_category_name}", leave=True, file=sys.stdout) as pbar:
                    for fut in as_completed(futures):
                        if _should_stop():
                            raise KeyboardInterrupt
                        try:
                            res = fut.result()
                            if res:
                                unique_links.append(res)
                        except Exception:
                            pass
                        finally:
                            pbar.update(1)
        except KeyboardInterrupt:
            logger.warning("Interrupted during link filtering; cancelling…")
            try:
                ex.shutdown(wait=False, cancel_futures=True)  # type: ignore
            except Exception:
                pass
            return pd.DataFrame()

        unique_links = list(dict.fromkeys(unique_links))
        if _should_stop():
            return pd.DataFrame()

        logger.info(f"{name}: There are {len(unique_links)} new links to scrape.")
        scrapers_to_run = scraper.get_scrapers()

        # Scrape in batches
        for i in range(0, len(unique_links), batch_size):
            if _should_stop():
                break
            article_scraped = {}
            ul = unique_links[i : i + batch_size]
            try:
                try:
                    logger.info(
                        f"Scraping batch {extract_domain(url)}: {int((i/batch_size)+1)}/{round((len(unique_links)/batch_size)+0.5)}"
                    )
                except Exception:
                    if len(unique_links) > 0:
                        logger.info(f"Scraping batch {extract_domain(url)}: {i}/{len(unique_links)}")

                already_run = []
                for scraper_to_run in scrapers_to_run:
                    if _should_stop():
                        raise KeyboardInterrupt
                    if scraper_to_run == "default":
                        scraper_to_run = scraper_dict["default"]
                        if scraper_to_run in already_run:
                            continue
                    article_scraped[scraper_to_run] = asyncio.run(scraper_dict[scraper_to_run](ul))
                    already_run.append(scraper_to_run)

                if isinstance(article_scraped[scraper_to_run], pd.DataFrame):
                    webscrapes_df = scraper.collate_scraper_results(article_scraped, scraper_dict)
                    if webscrapes_df.empty:
                        continue
                    webscrapes_df = save.saving_articles(webscrapes_df, infer_datetime=True)

                    print(f"Saving {len(webscrapes_df)} articles...")
                    _append_results_to_csv(webscrapes_df, out_csv_path)

            except KeyboardInterrupt:
                logger.warning("Interrupted during batch scraping; stopping…")
                break
            except Exception as e:
                traceback.print_exc()
                logger.info(f"Restarting scraper: {e}")

                # Rebuild scraper and retry once
                scraper = WebScraperV2(
                    url, pages_urls=pages_urls, anti_robot=anti_robot,
                    load_more_button=load_more_button, alt_source_domain=alt_source_domain,
                    config_data=config_data,
                )
                scraper_dict = {
                    "Interactive": scraper.run_interactive_scraper,
                    "Newsplease": scraper.run_newsplease_scraper,
                    "default": "Newsplease",
                }
                try:
                    already_run = []
                    for scraper_to_run in scrapers_to_run:
                        if _should_stop():
                            raise KeyboardInterrupt
                        if scraper_to_run == "default":
                            scraper_to_run = scraper_dict["default"]
                            if scraper_to_run in already_run:
                                continue
                        article_scraped[scraper_to_run] = asyncio.run(scraper_dict[scraper_to_run](ul))
                        already_run.append(scraper_to_run)

                    if isinstance(article_scraped[scraper_to_run], pd.DataFrame):
                        webscrapes_df = scraper.collate_scraper_results(article_scraped, scraper_dict)
                        if webscrapes_df.empty:
                            continue
                        webscrapes_df = save.saving_articles(webscrapes_df, infer_datetime=True)

                        print(f"Saving {len(webscrapes_df)} articles...")
                        _append_results_to_csv(webscrapes_df, out_csv_path)

                except KeyboardInterrupt:
                    logger.warning("Interrupted during retry; stopping…")
                    break
                except Exception as e2:
                    logger.info(f"Error while scraping: {e2}")
                    continue

            if isinstance(webscrapes_df, pd.DataFrame):
                new_articles = pd.concat([new_articles, webscrapes_df], ignore_index=True)

        return new_articles

    except KeyboardInterrupt:
        logger.warning("KeyboardInterrupt caught in webscrape(); exiting early.")
        return pd.DataFrame()
    except Exception as e:
        logger.info(f"Error: {e}")
        logger.info(traceback.format_exc())
        return None

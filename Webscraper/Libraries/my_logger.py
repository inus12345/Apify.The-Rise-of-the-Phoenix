
import logging, sys

def setup_logger(name: str = "Scraper", level: str = "INFO"):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(h)
    for noisy in ["urllib3","selenium","newsplease","readability","newspaper","dateparser","langdetect"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return logger

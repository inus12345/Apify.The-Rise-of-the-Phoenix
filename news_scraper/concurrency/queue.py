"""Job queue for managing scraping jobs across multiple workers."""
import uuid
import time
import json
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from datetime import datetime

from ..database.session import get_session


@dataclass
class Job:
    """Represents a scraping job in the queue."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    site_name: str = ""
    url: str = ""
    mode: str = "incremental"  # incremental, backfill
    status: str = "pending"  # pending, running, completed, failed
    priority: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    args: Dict[str, Any] = field(default_factory=dict)


class JobQueue:
    """
    Simple job queue for managing scraping jobs.
    
    Supports:
    - Adding jobs with priority
    - Processing jobs concurrently via worker pool
    - Persisting job state to database
    - Resuming failed jobs
    """
    
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.pending_jobs: List[Job] = []
        self.running_jobs: Dict[str, Job] = {}
        self.completed_jobs: Dict[str, Job] = {}
        self.failed_jobs: Dict[str, Job] = {}
    
    def add_job(
        self,
        site_name: str,
        url: str,
        mode: str = "incremental",
        priority: int = 0,
        args: Optional[Dict[str, Any]] = None
    ) -> str:
        """Add a new job to the queue."""
        from ..database.models import ScrapedArticle
        
        # Check if site already exists in DB
        session_gen = get_session()
        db = next(session_gen)
        
        try:
            existing = db.query(ScrapedArticle).filter(
                ScrapedArticle.url == url
            ).first()
            
            job_args = args or {}
            
            # Set appropriate mode based on arguments
            if "backfill" in str(job_args):
                mode = "backfill"
            
            if "cutoff_date" in job_args:
                job_args["date_cutoff"] = job_args["cutoff_date"]
            
            if "max_pages" in job_args:
                job_args["max_pages"] = job_args["max_pages"]
            
            new_job = Job(
                site_name=site_name,
                url=url,
                mode=mode,
                priority=priority,
                args=job_args
            )
            
            self.pending_jobs.append(new_job)
            self._sort_queue()
            
            return job_args.get("id", new_job.id)
        
        finally:
            db.close()
    
    def _sort_queue(self):
        """Sort pending jobs by priority (descending)."""
        self.pending_jobs.sort(key=lambda j: -j.priority)
    
    def submit_scrape(
        self,
        site_name: str,
        url: str,
        mode: str = "incremental",
        backfill_args: Optional[Dict[str, Any]] = None,
        priority: int = 0
    ) -> Optional[str]:
        """
        Submit a scrape job to the queue.
        
        Args:
            site_name: Name of the site to scrape
            url: URL of the site (used for existence check)
            mode: 'incremental' or 'backfill'
            backfill_args: Optional arguments for backfill mode
            priority: Job priority (higher numbers = more important)
            
        Returns:
            Job ID if job was queued, None if site not found
        """
        # Create a unique job ID based on URL and timestamp
        from datetime import datetime
        job_id = f"{url[:50]}_{datetime.now().strftime('%Y%m%d')}"
        
        job_args = {"id": job_id}
        return self.add_job(
            site_name=site_name,
            url=url,
            mode=mode,
            priority=priority,
            args=job_args
        )
    
    def _next_pending_job(self) -> Optional[Job]:
        """Get next pending job that is ready to run."""
        # Skip failed jobs with retries left (simple retry logic)
        for i in range(len(self.pending_jobs)):
            job = self.pending_jobs[i]
            
            if job.status == "pending":
                return job
        
        return None
    
    def _job_complete(self, job: Job, result: Dict[str, Any]):
        """Mark a job as completed or failed."""
        job.status = "completed" if not result.get("error") else "failed"
        job.completed_at = datetime.now()
        
        # Remove from pending list
        if job in self.pending_jobs:
            self.pending_jobs.remove(job)
        
        # Move to appropriate completion queue
        if job.status == "completed":
            self.completed_jobs[job.id] = job
        
        elif job.status == "failed":
            failed_count = getattr(job, "_retry_count", 0) + 1
            
            # Don't retry more than 3 times
            if failed_count < 3:
                job.status = "pending"
                job._retry_count = getattr(job, "_retry_count", 0) + 1
                
                # Move to end of pending queue for later retry
                self.pending_jobs.remove(job)
                self.pending_jobs.append(job)
            else:
                self.failed_jobs[job.id] = job
    
    def _process_job(self, job: Job, callback: Callable):
        """Process a single job."""
        from ..scraping.engine import ScraperEngine
        
        job.started_at = datetime.now()
        self.running_jobs[job.id] = job
        
        try:
            # Get site config from URL
            from ..scraping.config_registry import SiteConfigRegistry
            
            session_gen = get_session()
            db = next(session_gen)
            
            try:
                registry = SiteConfigRegistry(db)
                site_config = registry.get_site_by_url(job.url)
                
                if not site_config:
                    result = {"error": f"Site not found in DB: {job.url}"}
                else:
                    # Run scraper with job arguments
                    enable_rate_limiting = True
                    engine = ScraperEngine(enable_rate_limiting=enable_rate_limiting)
                    
                    args = job.args or {}
                    
                    # Determine mode and backfill args
                    mode = args.get("mode", job.mode)
                    date_cutoff = args.get("date_cutoff")
                    max_pages = args.get("max_pages")
                    
                    # Add incremental scrape to pending list for later
                    if not isinstance(args.get('id'), str):
                        id = args.get('id') or f"{job.url[:50]}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                        engine._pending_scrape_jobs[(site_config.id, id)] = {
                            "priority": args.get("priority", 0)
                        }
                    # Add scraping to pending list
                    elif job.args.get('id'):
                        engine._pending_scrape_jobs[(site_config.id, job.args['id'])] = {
                            "priority": args.get("priority", 0)
                        }
                    
                    stats = engine.scrape_site(site_config, db, mode=mode, 
                                               enable_rate_limiting=enable_rate_limiting,
                                               date_cutoff=date_cutoff,
                                               max_pages=max_pages)
                    
                    result = stats
                    
                self._job_complete(job, result)
                
            except Exception as e:
                logger.error(f"Error processing job {job.id}: {e}")
                result = {"error": str(e)}
            
        finally:
            db.close()
    
    def run_all(self, callback: Optional[Callable] = None):
        """Process all jobs in the queue."""
        from ..scraping.config_registry import SiteConfigRegistry
        
        pending_count = len(self.pending_jobs)
        
        if not pending_count:
            return
        
        print(f"Queue has {pending_count} pending job(s)")
        
        # Process jobs concurrently up to max_workers
        for _ in range(pending_count):
            if callback:
                try:
                    callback()
                except Exception as e:
                    import traceback
                    traceback.print_exc()
            
            time.sleep(1)  # Rate limiting between jobs


import logging
logger = logging.getLogger(__name__)
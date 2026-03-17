CREATE TABLE site_configs (
	id INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	url VARCHAR(500) NOT NULL, 
	domain VARCHAR(255), 
	notes TEXT, 
	category_url_pattern VARCHAR(500), 
	num_pages_to_scrape INTEGER, 
	article_selector VARCHAR(255), 
	title_selector VARCHAR(255), 
	author_selector VARCHAR(255), 
	date_selector VARCHAR(255), 
	body_selector VARCHAR(255), 
	preferred_scraper_type VARCHAR(50), 
	uses_javascript BOOLEAN, 
	active BOOLEAN, 
	status VARCHAR(50), 
	created_at DATETIME, 
	updated_at DATETIME, 
	last_scraped DATETIME, 
	last_successful_scrape DATETIME, 
	last_validation_time DATETIME, country VARCHAR(100), server_header VARCHAR(255), server_vendor VARCHAR(255), hosting_provider VARCHAR(255), ip_address VARCHAR(64), technology_stack_summary TEXT, location VARCHAR(100), description TEXT, language VARCHAR(10), 
	PRIMARY KEY (id), 
	UNIQUE (url)
);
CREATE INDEX ix_site_configs_domain ON site_configs (domain);
CREATE TABLE site_categories (
	id INTEGER NOT NULL, 
	site_config_id INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	url VARCHAR(500) NOT NULL, 
	max_pages INTEGER, 
	created_at DATETIME, 
	updated_at DATETIME, page_url_pattern VARCHAR(500), start_page INTEGER DEFAULT 1, active BOOLEAN DEFAULT 1, 
	PRIMARY KEY (id), 
	FOREIGN KEY(site_config_id) REFERENCES site_configs (id)
);
CREATE TABLE scraped_articles (
	id INTEGER NOT NULL, 
	url VARCHAR(1000) NOT NULL, 
	source_url_hash VARCHAR(32) NOT NULL, 
	title TEXT, 
	body TEXT, 
	description TEXT, 
	authors VARCHAR(500), 
	date_publish DATETIME, 
	date_download DATETIME, 
	image_url VARCHAR(1000), 
	source_domain VARCHAR(255), 
	language VARCHAR(10), 
	site_config_id INTEGER NOT NULL, 
	scrape_status VARCHAR(20), 
	error_message TEXT, 
	is_validated BOOLEAN, 
	validation_score INTEGER, 
	created_at DATETIME, 
	updated_at DATETIME, canonical_url VARCHAR(1000), section VARCHAR(255), tags JSON, scrape_date DATETIME, image_links JSON, extra_links JSON, word_count INTEGER, reading_time_minutes INTEGER, raw_metadata JSON, content_hash VARCHAR(64), scraper_engine_used VARCHAR(50), 
	PRIMARY KEY (id), 
	FOREIGN KEY(site_config_id) REFERENCES site_configs (id)
);
CREATE INDEX ix_scraped_articles_source_url_hash ON scraped_articles (source_url_hash);
CREATE INDEX idx_url_hash_site ON scraped_articles (source_url_hash, site_config_id);
CREATE TABLE scrape_runs (
	id INTEGER NOT NULL, 
	site_config_id INTEGER NOT NULL, 
	started_at DATETIME, 
	completed_at DATETIME, 
	status VARCHAR(50), 
	pages_scraped INTEGER, 
	articles_found INTEGER, 
	articles_saved INTEGER, 
	articles_skipped INTEGER, 
	error_count INTEGER, 
	last_error TEXT, 
	csv_export_path VARCHAR(500), 
	json_export_path VARCHAR(500), 
	PRIMARY KEY (id), 
	FOREIGN KEY(site_config_id) REFERENCES site_configs (id)
);
CREATE TABLE validation_runs (
	id INTEGER NOT NULL, 
	scraped_article_id INTEGER NOT NULL, 
	started_at DATETIME, 
	completed_at DATETIME, 
	status VARCHAR(50), 
	is_validated BOOLEAN, 
	validation_score INTEGER, 
	validation_notes TEXT, 
	llm_model VARCHAR(255), 
	prompt_tokens INTEGER, 
	completion_tokens INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(scraped_article_id) REFERENCES scraped_articles (id)
);
CREATE TABLE scrape_logs (
	id INTEGER NOT NULL, 
	site_config_id INTEGER NOT NULL, 
	scrape_run_id INTEGER, 
	timestamp DATETIME, 
	level VARCHAR(20), 
	event_type VARCHAR(50), 
	message TEXT NOT NULL, 
	extra_data JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(site_config_id) REFERENCES site_configs (id), 
	FOREIGN KEY(scrape_run_id) REFERENCES scrape_runs (id)
);
CREATE INDEX ix_scrape_logs_timestamp ON scrape_logs (timestamp);
CREATE TABLE site_technologies (
	id INTEGER NOT NULL, 
	site_config_id INTEGER NOT NULL, 
	technology_name VARCHAR(255) NOT NULL, 
	technology_type VARCHAR(100), 
	version VARCHAR(100), 
	confidence_score FLOAT, 
	detection_source VARCHAR(100), 
	notes TEXT, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_site_technology UNIQUE (site_config_id, technology_name, version), 
	FOREIGN KEY(site_config_id) REFERENCES site_configs (id)
);
CREATE INDEX ix_site_technologies_site_config_id ON site_technologies (site_config_id);
CREATE TABLE scrape_strategies (
	id INTEGER NOT NULL, 
	site_config_id INTEGER NOT NULL, 
	scraper_engine VARCHAR(50), 
	fallback_engine_chain JSON, 
	content_parser VARCHAR(50), 
	browser_automation_tool VARCHAR(50), 
	rendering_required BOOLEAN, 
	requires_proxy BOOLEAN, 
	proxy_region VARCHAR(100), 
	login_required BOOLEAN, 
	auth_strategy VARCHAR(255), 
	anti_bot_protection VARCHAR(255), 
	blocking_signals JSON, 
	bypass_techniques JSON, 
	request_headers JSON, 
	cookie_preset JSON, 
	rate_limit_per_minute INTEGER, 
	notes TEXT, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(site_config_id) REFERENCES site_configs (id)
);
CREATE UNIQUE INDEX ix_scrape_strategies_site_config_id ON scrape_strategies (site_config_id);
CREATE TABLE spider_diagrams (
	id INTEGER NOT NULL, 
	site_config_id INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	version INTEGER, 
	entrypoint_url VARCHAR(1000) NOT NULL, 
	is_active BOOLEAN, 
	notes TEXT, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_spider_diagram_version UNIQUE (site_config_id, name, version), 
	FOREIGN KEY(site_config_id) REFERENCES site_configs (id)
);
CREATE INDEX ix_spider_diagrams_site_config_id ON spider_diagrams (site_config_id);
CREATE TABLE llm_assessment_runs (
	id INTEGER NOT NULL, 
	site_config_id INTEGER NOT NULL, 
	trigger_type VARCHAR(50), 
	scope VARCHAR(100), 
	status VARCHAR(50), 
	llm_model VARCHAR(255), 
	prompt_version VARCHAR(50), 
	started_at DATETIME, 
	completed_at DATETIME, 
	total_lines INTEGER, 
	lines_flagged INTEGER, 
	lines_applied INTEGER, 
	summary TEXT, 
	error_message TEXT, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(site_config_id) REFERENCES site_configs (id)
);
CREATE INDEX ix_llm_assessment_runs_site_config_id ON llm_assessment_runs (site_config_id);
CREATE TABLE spider_nodes (
	id INTEGER NOT NULL, 
	spider_diagram_id INTEGER NOT NULL, 
	node_key VARCHAR(100) NOT NULL, 
	node_type VARCHAR(50) NOT NULL, 
	url_pattern VARCHAR(1000), 
	selector VARCHAR(255), 
	extraction_target JSON, 
	pagination_rule VARCHAR(255), 
	visit_order INTEGER, 
	active BOOLEAN, 
	notes TEXT, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_spider_node_key UNIQUE (spider_diagram_id, node_key), 
	FOREIGN KEY(spider_diagram_id) REFERENCES spider_diagrams (id)
);
CREATE INDEX ix_spider_nodes_spider_diagram_id ON spider_nodes (spider_diagram_id);
CREATE TABLE llm_assessment_lines (
	id INTEGER NOT NULL, 
	assessment_run_id INTEGER NOT NULL, 
	line_number INTEGER NOT NULL, 
	entity_type VARCHAR(100) NOT NULL, 
	entity_id INTEGER, 
	field_name VARCHAR(100) NOT NULL, 
	current_value TEXT, 
	suggested_value TEXT, 
	recommended_action VARCHAR(50), 
	reasoning TEXT, 
	confidence_score FLOAT, 
	status VARCHAR(50), 
	reviewed_by VARCHAR(255), 
	reviewed_at DATETIME, 
	applied_at DATETIME, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_assessment_line_number UNIQUE (assessment_run_id, line_number), 
	FOREIGN KEY(assessment_run_id) REFERENCES llm_assessment_runs (id)
);
CREATE INDEX ix_llm_assessment_lines_assessment_run_id ON llm_assessment_lines (assessment_run_id);
CREATE TABLE spider_edges (
	id INTEGER NOT NULL, 
	spider_diagram_id INTEGER NOT NULL, 
	from_node_id INTEGER NOT NULL, 
	to_node_id INTEGER NOT NULL, 
	traversal_type VARCHAR(50) NOT NULL, 
	link_selector VARCHAR(255), 
	condition_expression VARCHAR(255), 
	priority INTEGER, 
	notes TEXT, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(spider_diagram_id) REFERENCES spider_diagrams (id), 
	FOREIGN KEY(from_node_id) REFERENCES spider_nodes (id), 
	FOREIGN KEY(to_node_id) REFERENCES spider_nodes (id)
);
CREATE INDEX ix_spider_edges_spider_diagram_id ON spider_edges (spider_diagram_id);

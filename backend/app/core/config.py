from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: str = "dev"
    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: str = "postgresql+asyncpg://dpb:dpb_pass@localhost:5432/dpb"
    REDIS_URL: str = "redis://localhost:6379/0"

    JWT_SECRET: str = "change-me-dev-secret"
    JWT_ALG: str = "HS256"
    ACCESS_TTL: int = 900
    REFRESH_TTL: int = 604800
    RATE_LIMIT: str = "100/minute"

    ADK_URL: str = "http://adk-service:9000"
    ADK_SECRET: str = "change-me-adk-secret"
    GOOGLE_API_KEY: str = "REPLACE_ME_LATER"

    SMTP_HOST: str = "mailhog"
    SMTP_PORT: int = 1025
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "no-reply@demandplanner.local"
    APP_BASE_URL: str = "http://localhost:3000"

    KPI_CACHE_TTL: int = 300
    # Dashboard cache TTLs (seconds): volatile operational data vs. slow reference data.
    DASHBOARD_CACHE_TTL: int = 900  # 15 min for executive/operational metrics
    DASHBOARD_REFERENCE_TTL: int = 3600  # 1 hour for filter option lists

    # Upload System Configuration
    # File size limits (in bytes)
    UPLOAD_MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB default
    UPLOAD_MIN_ASYNC_SIZE: int = 10 * 1024 * 1024  # 10MB threshold for async processing
    UPLOAD_MAX_FILE_SIZE_HARD: int = 1024 * 1024 * 1024  # 1GB hard limit

    # Supported file types
    UPLOAD_ALLOWED_EXTENSIONS: set[str] = {
        ".csv", ".xlsx", ".xls", ".json"
    }

    # Processing timeouts and thresholds
    UPLOAD_PARSE_TIMEOUT: int = 300  # 5 minutes
    UPLOAD_VALIDATE_TIMEOUT: int = 600  # 10 minutes
    UPLOAD_IMPORT_TIMEOUT: int = 1800  # 30 minutes

    # Validation thresholds
    UPLOAD_MAX_ERROR_DISPLAY: int = 1000  # Maximum errors to display in UI
    UPLOAD_WARNING_THRESHOLD: int = 100  # Show warning if error count exceeds this
    UPLOAD_SAMPLE_SIZE: int = 10  # Number of rows to show in preview

    # Upload staging
    UPLOAD_STAGING_DIR: str = "tmp/uploads"
    UPLOAD_CLEANUP_AFTER_HOURS: int = 24  # Cleanup temporary files after 24 hours

    # File Parser Configuration
    PARSER_CHUNK_SIZE: int = 10000  # Rows per chunk for streaming
    PARSER_SAMPLE_SIZE: int = 10  # Rows to include in preview sample
    PARSER_MAX_MEMORY_MB: int = 500  # Maximum memory usage target in MB
    PARSER_CSV_DELIMITERS: list[str] = [",", "\t", ";", "|"]  # Supported CSV delimiters
    PARSER_AUTO_DETECT_ENCODING: bool = True  # Whether to auto-detect file encoding
    PARSER_DEFAULT_ENCODING: str = "utf-8"  # Default encoding if detection fails

    # Validation Configuration
    # Validation thresholds
    VALIDATION_MAX_ERRORS_DISPLAY: int = 1000  # Maximum errors to display in UI
    VALIDATION_WARNING_THRESHOLD: int = 100  # Show warning if error count exceeds this
    VALIDATION_BATCH_SIZE: int = 10000  # Rows per batch for validation processing
    VALIDATION_STOP_ON_FIRST_ERROR: bool = False  # Stop validation on first error (useful for debugging)

    # Data quality thresholds
    VALIDATION_MISSING_VALUE_THRESHOLD: float = 0.5  # Allow up to 50% missing values per column
    VALIDATION_DUPLICATE_THRESHOLD: int = 1  # Number of duplicates to allow before error
    VALIDATION_OUTLIER_STD_DEV: float = 3.0  # Standard deviations for outlier detection

    # Business rule parameters
    VALIDATION_REVENUE_TOLERANCE: float = 0.01  # 1% tolerance for revenue calculation validation
    VALIDATION_ALLOW_FUTURE_DATES: bool = False  # Allow future dates in historical data
    VALIDATION_MIN_QUANTITY: float = 0  # Minimum allowed quantity (non-negative)
    VALIDATION_MAX_QUANTITY: int | None = None  # Maximum allowed quantity (None = unlimited)
    VALIDATION_MIN_PRICE: float = 0  # Minimum allowed price (non-negative)
    VALIDATION_MAX_PRICE: int | None = None  # Maximum allowed price (None = unlimited)

    # Validation stages to enable
    VALIDATION_ENABLE_SCHEMA: bool = True  # Enable schema validation
    VALIDATION_ENABLE_BUSINESS_RULES: bool = True  # Enable business rules validation
    VALIDATION_ENABLE_DATA_QUALITY: bool = True  # Enable data quality checks

    # Validation performance options
    VALIDATION_PARALLEL_PROCESSING: bool = True  # Enable parallel processing for large datasets


settings = Settings()

from pydantic import BaseModel


class ActualsUploadOut(BaseModel):
    uploaded: int
    skipped: int
    session_id: str
    matched_items: int  # rows whose item_id exists in this session's forecasts
    errors: list[str]  # first N human-readable row errors (capped)

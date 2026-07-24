from enum import Enum


class WorkspaceDir(str, Enum):
    CURLS = "curls"
    REAL_RESPONSES = "real_responses"
    REAL_REQUESTS = "real_requests"
    EXTRACTORS = "extractors"
    TEMP_EXTRACTORS = "temp_extractors"

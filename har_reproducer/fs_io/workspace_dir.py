from enum import Enum


class WorkspaceDir(str, Enum):
    CURLS = "curls"
    REAL_RESPONSES = "real_responses"
    ORIGINAL_RESPONSES = "original_responses"
    ORIGINAL_REQUESTS = "original_requests"
    EXTRACTORS = "extractors"
    TEMP_EXTRACTORS = "temp_extractors"
    MITM_CAPTURE = "mitm_capture"
    REPLAYS = "replays"